"""Bounded source loading and immutable CharacterSnapshotV1 envelopes.

This module is the only place that interprets a caller-provided reference.
Keeping that decision separate from derivation prevents a missing path such as
``fixtures/pc-123.json`` from silently becoming D&D Beyond character ``123``.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import copy
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import socket
from urllib.parse import unquote, urlparse
import urllib.error
import urllib.request

from . import (ddb_registry, errors, registry as semantic_registry,
               source_field_registry)


SNAPSHOT_SCHEMA = "charactercheck.character-snapshot"
SNAPSHOT_VERSION = 1
SOURCE_SCHEMA = "ddb-character-service-v5.partial"
_SOURCE_SCHEMA_CONTRACT = {
    "name": SOURCE_SCHEMA,
    "required": ["id", "stats", "classes", "inventory", "modifiers"],
    "ability_ids": [1, 2, 3, 4, 5, 6],
    "snapshot_version": 1,
    "ddb_config_registry": ddb_registry.REGISTRY_FINGERPRINT,
    "item_semantic_gaps": {
        code: list(semantic_registry.ITEM_SEMANTIC_GAPS[code]["affects"])
        for code in sorted(semantic_registry.ITEM_SEMANTIC_GAP_CODES)
    },
    "unscoped_definition_semantic_gap_policy": "unknown-global-scope",
    "root_item_weapon_property_scope_requires": (
        "canonical-damage-dice-and-known-integer-attack-type"),
    "source_coverage_boolean_keys": [
        "unclassified_top_level_omitted",
        "unclassified_nested_omitted",
        "semantic_values_omitted",
    ],
    "source_coverage_family_scope_key": "scoped_mechanical_omissions",
    "source_field_registry": source_field_registry.REGISTRY_FINGERPRINT,
    "source_field_empty_optional_policy": (
        "none-false-empty-string-list-object-do-not-create-scope;zero-is-data"),
}
SOURCE_SCHEMA_FINGERPRINT = "sha256:" + hashlib.sha256(
    json.dumps(_SOURCE_SCHEMA_CONTRACT, sort_keys=True,
               separators=(",", ":")).encode("utf-8")).hexdigest()
RULES_PROFILE = "srd-5.2.1-partial"

MAX_INPUT_BYTES = 8 * 1024 * 1024
# A pretty-printed CharacterSnapshotV1 can be larger than its accepted raw
# source because it adds a versioned envelope and indentation. This separate
# bound guarantees the documented local snapshot -> diff round trip while
# keeping the parser bounded.
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 64
MAX_NODES = 100_000
MAX_STRING_LENGTH = 262_144
MAX_KEY_LENGTH = 1_024
MAX_COLLECTION_ITEMS = 25_000
MAX_INVENTORY_ITEMS = 5_000
MAX_MODIFIERS = 20_000
MAX_ID_DIGITS = 20
MAX_CONTAINER_HOPS = 256
MAX_NUMBER_TOKEN_LENGTH = 128
MAX_ITEM_WEIGHT = 1_000_000
MAX_ITEM_QUANTITY = 1_000_000
MAX_MECHANICAL_MAGNITUDE = 1_000_000
MAX_SUPPORTED_BASE_ARMOR_CLASS = 100
# DDB character-service v5 adapter facts, loaded from the pinned offline
# registry. Presence here establishes identity only; it does not claim that the
# engine implements a value's rules semantics.
KNOWN_DDB_ARMOR_TYPE_IDS = frozenset(ddb_registry.ARMOR_TYPES)
KNOWN_DDB_ATTACK_TYPE_IDS = frozenset(ddb_registry.RANGE_TYPES)
KNOWN_DDB_DAMAGE_TYPES = frozenset(ddb_registry.DAMAGE_TYPES.values())
KNOWN_DDB_DAMAGE_DIE_VALUES = frozenset(ddb_registry.DICE_VALUES)
_WEAPON_PROPERTY_ID_BY_NAME = {
    name: identifier
    for identifier, name in ddb_registry.WEAPON_PROPERTIES.items()
}
MAX_DAMAGE_DICE_COUNT = 100
MAX_DAMAGE_DIE_VALUE = 1_000

_ID_RE = re.compile(r"^[0-9]+$")
_DAMAGE_DICE_RE = re.compile(r"^([1-9][0-9]{0,2})d([1-9][0-9]{0,3})$")
_DDB_PATH_RE = re.compile(r"^/characters/([0-9]+)/?$")
_PATH_HINT_RE = re.compile(r"(?:^\.?\.?[/\\]|[/\\]|\.json$)", re.I)
_ALLOWED_DDB_HOSTS = {"dndbeyond.com", "www.dndbeyond.com"}


@dataclass(frozen=True)
class LoadedCharacter:
    """A validated source document and the metadata needed for a snapshot."""

    character: dict
    adapter: str
    source_id: str
    observed_at: str
    source_schema: str = SOURCE_SCHEMA
    source_schema_fingerprint: str = SOURCE_SCHEMA_FINGERPRINT
    source_revision: str = None
    source_coverage: dict = None


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


_OBSERVED_AT_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z$")


def _parse_observed_at(value):
    """Parse the snapshot's canonical UTC observation timestamp."""
    if not isinstance(value, str) or not _OBSERVED_AT_RE.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo == timezone.utc else None


def _safe_source_id(value):
    """Return a non-path source id suitable for output metadata."""
    text = str(value or "")
    return text if _valid_id(text) else "local"


def _valid_id(text):
    return bool(_ID_RE.fullmatch(text) and 0 < len(text) <= MAX_ID_DIGITS
                and not text.startswith("0") and int(text) > 0)


def parse_ref(ref, *, allow_local=True):
    """Classify exactly one supported reference shape.

    Returns ``(kind, value)`` where kind is ``id`` or ``path``. Arbitrary
    digits embedded in an otherwise-invalid string are never extracted.
    """
    if isinstance(ref, os.PathLike):
        ref = os.fspath(ref)
    if not isinstance(ref, str) or not ref.strip():
        raise errors.bad_ref(ref)
    text = ref.strip()

    if _ID_RE.fullmatch(text):
        if _valid_id(text):
            return "id", text
        raise errors.bad_ref(ref)

    parsed = urlparse(text)
    if parsed.scheme in ("http", "https"):
        try:
            has_port = parsed.port is not None
        except ValueError:
            raise errors.bad_ref(ref)
        if (parsed.scheme != "https" or parsed.username is not None
                or parsed.password is not None or has_port
                or (parsed.hostname or "").lower() not in _ALLOWED_DDB_HOSTS):
            raise errors.bad_ref(ref)
        match = _DDB_PATH_RE.fullmatch(parsed.path)
        if not match or parsed.params or parsed.query or parsed.fragment:
            raise errors.bad_ref(ref)
        character_id = match.group(1)
        if not _valid_id(character_id):
            raise errors.bad_ref(ref)
        return "id", character_id

    if parsed.scheme == "file":
        if not allow_local:
            raise errors.local_files_disabled()
        if parsed.netloc not in ("", "localhost"):
            raise errors.bad_ref(ref)
        return "path", _validated_path(Path(unquote(parsed.path)))

    if parsed.scheme:
        raise errors.bad_ref(ref)

    if not allow_local:
        # Deny path-shaped input without touching the filesystem, but do not
        # mislabel arbitrary malformed references as capability requests.
        if _PATH_HINT_RE.search(text):
            raise errors.local_files_disabled()
        raise errors.bad_ref(ref)
    path = Path(os.path.expanduser(text))
    if path.is_file():
        return "path", _validated_path(path)
    if _PATH_HINT_RE.search(text) or any(ch.isdigit() for ch in text):
        # Digit-bearing missing paths are the dangerous case: older versions
        # extracted the first digits and made an unrelated network request.
        raise errors.missing_file()
    raise errors.bad_ref(ref)


def _validated_path(path):
    """Enforce the local-file capability's conservative path policy."""
    try:
        absolute = path.absolute()
        if any(component.is_symlink()
               for component in (absolute, *absolute.parents)):
            raise errors.file_policy("symbolic links are not accepted")
        if not path.is_file():
            raise errors.missing_file()
        return path.resolve(strict=True)
    except errors.CharacterCheckError:
        raise
    except (OSError, ValueError):
        raise errors.missing_file()


def _bounded_read(stream, *, limit=MAX_INPUT_BYTES):
    raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise errors.input_too_large(limit)
    return raw


def _decode_json(raw, ref_label):
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    except UnicodeDecodeError as exc:
        raise errors.bad_json(ref_label, f"invalid UTF-8 at byte {exc.start}")
    _precheck_nesting(text)
    try:
        value = json.loads(text, object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant,
                           parse_float=_finite_float,
                           parse_int=_bounded_int)
    except json.JSONDecodeError as exc:
        raise errors.bad_json(ref_label, f"JSON syntax at line {exc.lineno}, column {exc.colno}")
    except _UnsafeJSON as exc:
        raise errors.bad_json(ref_label, str(exc))
    except ValueError:
        # Python versions differ in how their integer-string conversion guard
        # reports enormous number tokens. Keep that implementation detail out
        # of the public boundary.
        raise errors.bad_json(ref_label, "numeric token is not supported")
    except RecursionError:
        raise errors.input_too_deep(MAX_DEPTH)
    except MemoryError:
        raise errors.input_limit("decoder memory", MAX_INPUT_BYTES)
    _validate_complexity(value)
    return value


class _UnsafeJSON(ValueError):
    pass


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise _UnsafeJSON(f"duplicate object key {key!r}")
        out[key] = value
    return out


def _reject_constant(value):
    raise _UnsafeJSON(f"non-finite number {value!r} is not valid input")


def _finite_float(value):
    if len(value) > MAX_NUMBER_TOKEN_LENGTH:
        raise _UnsafeJSON("numeric token exceeds the safety limit")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise _UnsafeJSON("non-finite numeric value is not valid input")
    return parsed


def _bounded_int(value):
    if len(value.lstrip("-")) > MAX_NUMBER_TOKEN_LENGTH:
        raise _UnsafeJSON("integer token exceeds the safety limit")
    return int(value)


def _precheck_nesting(text):
    """Bound nesting before the recursive standard-library decoder runs."""
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise errors.input_too_deep(MAX_DEPTH)
        elif char in "]}":
            depth = max(0, depth - 1)


def _validate_complexity(value):
    nodes = 0
    seen_containers = set()
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_NODES:
            raise errors.input_limit("JSON node count", MAX_NODES)
        if depth > MAX_DEPTH:
            raise errors.input_too_deep(MAX_DEPTH)
        if isinstance(current, str) and len(current) > MAX_STRING_LENGTH:
            raise errors.input_limit("string length", MAX_STRING_LENGTH)
        if isinstance(current, dict):
            identity = id(current)
            if identity in seen_containers:
                raise errors.cyclic_reference()
            seen_containers.add(identity)
            if len(current) > MAX_COLLECTION_ITEMS:
                raise errors.input_limit("object member count", MAX_COLLECTION_ITEMS)
            for key, child in current.items():
                if not isinstance(key, str):
                    raise errors.invalid_character("object keys must be strings")
                if len(key) > MAX_KEY_LENGTH:
                    raise errors.input_limit("object-key length", MAX_KEY_LENGTH)
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            identity = id(current)
            if identity in seen_containers:
                raise errors.cyclic_reference()
            seen_containers.add(identity)
            if len(current) > MAX_COLLECTION_ITEMS:
                raise errors.input_limit("array item count", MAX_COLLECTION_ITEMS)
            stack.extend((child, depth + 1) for child in current)
        elif current is None or isinstance(current, (str, bool, int)):
            pass
        elif isinstance(current, float):
            if not math.isfinite(current):
                raise errors.invalid_character("non-finite numbers are not supported")
        else:
            raise errors.invalid_character(
                f"unsupported in-memory JSON type {type(current).__name__}")


def _expect_type(character, key, expected, *, required=False):
    if key not in character:
        if required:
            raise errors.invalid_character(f"missing required field {key!r}")
        return
    if not isinstance(character[key], expected):
        label = expected.__name__ if isinstance(expected, type) else " or ".join(t.__name__ for t in expected)
        raise errors.invalid_character(f"field {key!r} must be {label}")


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _optional_number(obj, key, path):
    if key in obj and obj[key] is not None and not _number(obj[key]):
        raise errors.invalid_character(f"{path}.{key} must be a finite number or null")


def _optional_integer(obj, key, path):
    if key in obj and obj[key] is not None and not _integer(obj[key]):
        raise errors.invalid_character(f"{path}.{key} must be a finite integer or null")


def _optional_bounded_integer(obj, key, path, *,
                              limit=MAX_MECHANICAL_MAGNITUDE):
    _optional_integer(obj, key, path)
    value = obj.get(key)
    if value is not None and abs(value) > limit:
        raise errors.invalid_character(
            f"{path}.{key} exceeds the supported numeric safety range")


def _optional_bool(obj, key, path):
    if key in obj and obj[key] is not None and not isinstance(obj[key], bool):
        raise errors.invalid_character(f"{path}.{key} must be boolean or null")


def _optional_string(obj, key, path):
    if key in obj and obj[key] is not None and not isinstance(obj[key], str):
        raise errors.invalid_character(f"{path}.{key} must be a string or null")


def _optional_dict(obj, key, path):
    value = obj.get(key)
    if value is not None and not isinstance(value, dict):
        raise errors.invalid_character(f"{path}.{key} must be an object or null")
    return value or {}


def _optional_list(obj, key, path):
    value = obj.get(key)
    if value is not None and not isinstance(value, list):
        raise errors.invalid_character(f"{path}.{key} must be an array or null")
    return value or []


def canonical_damage_dice(damage):
    """Return a bounded, inert base-damage expression or ``None``.

    A DDB damage record also carries ``diceCount`` and ``diceValue``. When
    present, those structured fields must agree with ``diceString``. The
    canonical value is reconstructed from integers so player/source-authored
    text can never be copied into an agent-facing mechanics field.
    """
    if not isinstance(damage, dict):
        return None
    value = damage.get("diceString")
    if not isinstance(value, str):
        return None
    match = _DAMAGE_DICE_RE.fullmatch(value)
    if not match:
        return None
    count, sides = (int(part) for part in match.groups())
    if count > MAX_DAMAGE_DICE_COUNT or sides > MAX_DAMAGE_DIE_VALUE:
        return None
    if damage.get("diceCount") is not None \
            and damage.get("diceCount") != count:
        return None
    if damage.get("diceValue") is not None \
            and damage.get("diceValue") != sides:
        return None
    return f"{count}d{sides}"


def _validate_definition(definition, path, *, inventory_item=False):
    if not isinstance(definition, dict):
        raise errors.invalid_character(f"{path} must be an object")
    for key in ("bundleSize", "spellCastingAbilityId", "hitDice",
                "requiredLevel", "level"):
        _optional_integer(definition, key, path)
    for key in ("armorTypeId", "attackType"):
        _optional_bounded_integer(definition, key, path)
    _optional_bounded_integer(definition, "armorClass", path)
    _optional_number(definition, "weight", path)
    weight = definition.get("weight")
    if weight is not None and not 0 <= weight <= MAX_ITEM_WEIGHT:
        raise errors.invalid_character(
            f"{path}.weight must be in 0..{MAX_ITEM_WEIGHT}")
    _optional_integer(definition, "id", path)
    for key in ("canAttune", "canEquip", "isConsumable", "isContainer",
                "magic"):
        _optional_bool(definition, key, path)
    for key in ("name", "damageType"):
        _optional_string(definition, key, path)
    ability_id = definition.get("spellCastingAbilityId")
    if ability_id is not None and ability_id not in range(1, 7):
        raise errors.invalid_character(
            f"{path}.spellCastingAbilityId must be in 1..6 or null")
    damage = _optional_dict(definition, "damage", path)
    for key in ("diceCount", "diceValue", "diceMultiplier", "fixedValue"):
        _optional_bounded_integer(damage, key, f"{path}.damage")
    if damage.get("diceCount") is not None \
            and not 1 <= damage["diceCount"] <= MAX_DAMAGE_DICE_COUNT:
        raise errors.invalid_character(
            f"{path}.damage.diceCount is outside the supported range")
    if damage.get("diceValue") is not None \
            and not 1 <= damage["diceValue"] <= MAX_DAMAGE_DIE_VALUE:
        raise errors.invalid_character(
            f"{path}.damage.diceValue is outside the supported range")
    if damage.get("diceString") is not None \
            and not isinstance(damage.get("diceString"), str):
        raise errors.invalid_character(
            f"{path}.damage.diceString must be a string or null")
    armor_class = definition.get("armorClass")
    if (armor_class is not None
            and not 0 <= armor_class <= MAX_SUPPORTED_BASE_ARMOR_CLASS):
        raise errors.invalid_character(
            f"{path}.armorClass must be in "
            f"0..{MAX_SUPPORTED_BASE_ARMOR_CLASS} or null")
    for index, modifier in enumerate(_optional_list(definition, "grantedModifiers", path)):
        _validate_modifier(modifier, f"{path}.grantedModifiers[{index}]")
    for index, prop in enumerate(_optional_list(definition, "properties", path)):
        if not isinstance(prop, dict):
            raise errors.invalid_character(f"{path}.properties[{index}] must be an object")
        _optional_bounded_integer(prop, "id", f"{path}.properties[{index}]")
        name = prop.get("name")
        if not isinstance(name, str) or not name.strip():
            raise errors.invalid_character(
                f"{path}.properties[{index}].name must be a non-empty string")
    gaps = definition.get("_semanticGaps")
    if gaps is not None:
        if not isinstance(gaps, list) or any(
                not isinstance(code, str)
                or code not in semantic_registry.ITEM_SEMANTIC_GAP_CODES
                for code in gaps):
            raise errors.invalid_character(
                f"{path}._semanticGaps contains an unknown internal code")
    for index, feature in enumerate(_optional_list(
            definition, "classFeatures", path)):
        if not isinstance(feature, dict):
            raise errors.invalid_character(
                f"{path}.classFeatures[{index}] must be an object")
        _optional_integer(feature, "requiredLevel",
                          f"{path}.classFeatures[{index}]")
        child = feature.get("definition")
        if child is not None:
            _validate_definition(
                child, f"{path}.classFeatures[{index}].definition")


def _validate_modifier(modifier, path):
    if not isinstance(modifier, dict):
        raise errors.invalid_character(f"{path} must be an object")
    for key in ("type", "subType", "restriction", "friendlyTypeName",
                "friendlySubtypeName"):
        if key in modifier and modifier[key] is not None \
                and not isinstance(modifier[key], str):
            raise errors.invalid_character(f"{path}.{key} must be a string or null")
    _optional_bounded_integer(modifier, "value", path)
    for key in ("statId", "componentId"):
        _optional_integer(modifier, key, path)
    stat_id = modifier.get("statId")
    if stat_id is not None and stat_id not in range(1, 7):
        raise errors.invalid_character(f"{path}.statId must be in 1..6 or null")
    for key in ("isGranted",):
        _optional_bool(modifier, key, path)


def validate_character(character):
    """Validate the structural contract required by the derivation engine."""
    _validate_complexity(character)
    if not isinstance(character, dict):
        raise errors.invalid_character("character payload must be an object")
    _expect_type(character, "id", (int, str), required=True)
    if isinstance(character["id"], bool) or not _valid_id(str(character["id"])):
        raise errors.invalid_character("field 'id' must be a bounded positive numeric id")
    for key in ("stats", "classes", "inventory"):
        _expect_type(character, key, list, required=True)
    _expect_type(character, "modifiers", dict, required=True)
    _optional_string(character, "name", "character")
    if not character.get("name"):
        raise errors.invalid_character("character.name must be a non-empty string")
    if len(character["stats"]) != 6:
        raise errors.invalid_character("field 'stats' must contain exactly six abilities")
    if not character["classes"]:
        raise errors.invalid_character("field 'classes' must contain at least one class")
    if len(character["inventory"]) > MAX_INVENTORY_ITEMS:
        raise errors.input_limit("inventory item count", MAX_INVENTORY_ITEMS)
    stat_ids = set()
    for idx, stat in enumerate(character["stats"]):
        if not isinstance(stat, dict) or not isinstance(stat.get("id"), int) \
                or isinstance(stat.get("id"), bool):
            raise errors.invalid_character(f"stats[{idx}].id must be an integer")
        if stat["id"] not in range(1, 7) or stat["id"] in stat_ids:
            raise errors.invalid_character("stats must contain unique ability ids 1 through 6")
        stat_ids.add(stat["id"])
        if "value" not in stat or not _integer(stat.get("value")):
            raise errors.invalid_character(f"stats[{idx}].value must be an integer")
        if stat["value"] not in range(1, 21):
            raise errors.invalid_character(
                f"stats[{idx}].value must be in the supported base range 1..20")
    if stat_ids != set(range(1, 7)):
        raise errors.invalid_character("stats must contain unique ability ids 1 through 6")
    for idx, cls in enumerate(character["classes"]):
        if not isinstance(cls, dict):
            raise errors.invalid_character(f"classes[{idx}] must be an object")
        level = cls.get("level")
        if (not isinstance(level, int) or isinstance(level, bool)
                or level not in range(1, 21)):
            raise errors.invalid_character(
                f"classes[{idx}].level must be an integer in 1..20")
        _validate_definition(cls.get("definition"), f"classes[{idx}].definition")
        class_definition = cls["definition"]
        if not class_definition.get("name"):
            raise errors.invalid_character(
                f"classes[{idx}].definition.name must be a non-empty string")
        if class_definition.get("hitDice") not in (6, 8, 10, 12):
            raise errors.invalid_character(
                f"classes[{idx}].definition.hitDice must be one of 6, 8, 10, 12")
        subclass = cls.get("subclassDefinition")
        if subclass is not None:
            _validate_definition(subclass, f"classes[{idx}].subclassDefinition")
            for fidx, feature in enumerate(_optional_list(
                    subclass, "classFeatures", f"classes[{idx}].subclassDefinition")):
                if not isinstance(feature, dict):
                    raise errors.invalid_character(
                        f"classes[{idx}].subclassDefinition.classFeatures[{fidx}] must be an object")
                definition = feature.get("definition")
                _optional_integer(
                    feature, "requiredLevel",
                    f"classes[{idx}].subclassDefinition.classFeatures[{fidx}]")
                if definition is not None:
                    _validate_definition(definition,
                                         f"classes[{idx}].subclassDefinition.classFeatures[{fidx}].definition")
        for fidx, feature in enumerate(_optional_list(cls, "classFeatures", f"classes[{idx}]")):
            if not isinstance(feature, dict):
                raise errors.invalid_character(f"classes[{idx}].classFeatures[{fidx}] must be an object")
            definition = feature.get("definition")
            _optional_integer(feature, "requiredLevel",
                              f"classes[{idx}].classFeatures[{fidx}]")
            if definition is not None:
                _validate_definition(definition,
                                     f"classes[{idx}].classFeatures[{fidx}].definition")
        _optional_integer(cls, "hitDiceUsed", f"classes[{idx}]")
        hit_dice_used = cls.get("hitDiceUsed")
        if (hit_dice_used is not None
                and hit_dice_used not in range(0, level + 1)):
            raise errors.invalid_character(
                f"classes[{idx}].hitDiceUsed must be in 0..class level")
    if sum(cls["level"] for cls in character["classes"]) > 20:
        raise errors.invalid_character("combined class level must not exceed 20")
    inventory_ids = set()
    for idx, item in enumerate(character["inventory"]):
        if not isinstance(item, dict) or not isinstance(item.get("id"), (int, str)) \
                or isinstance(item.get("id"), bool):
            raise errors.invalid_character(f"inventory[{idx}].id must be an integer or string")
        normalized_item_id = str(item["id"])
        if normalized_item_id in inventory_ids:
            raise errors.invalid_character("inventory item ids must be unique")
        inventory_ids.add(normalized_item_id)
        parent = item.get("containerEntityId")
        if parent is not None and (not isinstance(parent, (int, str)) or isinstance(parent, bool)):
            raise errors.invalid_character(
                f"inventory[{idx}].containerEntityId must be an integer, string, or null")
        _validate_definition(item.get("definition"),
                             f"inventory[{idx}].definition",
                             inventory_item=True)
        bundle_size = (item.get("definition") or {}).get("bundleSize")
        if bundle_size is not None and bundle_size <= 0:
            raise errors.invalid_character(
                f"inventory[{idx}].definition.bundleSize must be positive or null")
        if bundle_size is not None and bundle_size > MAX_ITEM_QUANTITY:
            raise errors.invalid_character(
                f"inventory[{idx}].definition.bundleSize exceeds the safety limit")
        _optional_integer(item, "quantity", f"inventory[{idx}]")
        if (item.get("quantity") is not None
                and item["quantity"] not in range(1, MAX_ITEM_QUANTITY + 1)):
            raise errors.invalid_character(
                f"inventory[{idx}].quantity must be in 1..{MAX_ITEM_QUANTITY} or null")
        for key in ("equipped", "isAttuned"):
            _optional_bool(item, key, f"inventory[{idx}]")
    modifier_count = 0
    for bucket, modifiers in character["modifiers"].items():
        if not isinstance(modifiers, list):
            raise errors.invalid_character(f"modifier bucket {bucket!r} must be a list")
        modifier_count += len(modifiers)
        if any(not isinstance(modifier, dict) for modifier in modifiers):
            raise errors.invalid_character(f"modifier bucket {bucket!r} contains a non-object")
    if modifier_count > MAX_MODIFIERS:
        raise errors.input_limit("modifier count", MAX_MODIFIERS)
    for bucket, modifiers in character["modifiers"].items():
        for idx, modifier in enumerate(modifiers):
            _validate_modifier(modifier, f"modifiers.{bucket}[{idx}]")

    for key in ("overrideStats", "bonusStats", "classes", "inventory",
                "characterValues", "classSpells", "conditions", "feats",
                "spellSlots", "pactMagic", "customItems"):
        _optional_list(character, key, "character")
    for key in ("race", "background", "spells", "actions", "deathSaves",
                "currencies", "traits", "notes", "preferences"):
        _optional_dict(character, key, "character")
    if "baseHitPoints" not in character or not _integer(character.get("baseHitPoints")):
        raise errors.invalid_character("character.baseHitPoints must be an integer")
    if not 0 <= character["baseHitPoints"] <= MAX_MECHANICAL_MAGNITUDE:
        raise errors.invalid_character(
            "character.baseHitPoints is outside the supported numeric safety range")
    for key in ("bonusHitPoints", "overrideHitPoints",
                "removedHitPoints", "temporaryHitPoints", "currentXp",
                "alignmentId"):
        _optional_bounded_integer(character, key, "character")
    _optional_bool(character, "inspiration", "character")

    for idx, value in enumerate(character.get("characterValues") or []):
        if not isinstance(value, dict):
            raise errors.invalid_character(f"characterValues[{idx}] must be an object")
        for key in ("typeId", "valueId"):
            if (key in value and value[key] is not None
                    and (not isinstance(value[key], (int, str))
                         or isinstance(value[key], bool))):
                raise errors.invalid_character(f"characterValues[{idx}].{key} has an invalid type")

    for stat_key in ("overrideStats", "bonusStats"):
        seen = set()
        for idx, stat in enumerate(character.get(stat_key) or []):
            if not isinstance(stat, dict) or not isinstance(stat.get("id"), int) \
                    or isinstance(stat.get("id"), bool):
                raise errors.invalid_character(f"{stat_key}[{idx}].id must be an integer")
            if stat["id"] not in range(1, 7) or stat["id"] in seen:
                raise errors.invalid_character(f"{stat_key} ability ids must be unique and in 1..6")
            seen.add(stat["id"])
            _optional_integer(stat, "value", f"{stat_key}[{idx}]")
            value = stat.get("value")
            if (stat_key == "overrideStats" and value is not None
                    and value not in range(1, 31)):
                raise errors.invalid_character(
                    f"{stat_key}[{idx}].value must be in 1..30 or null")
            if (stat_key == "bonusStats" and value is not None
                    and value not in range(-30, 31)):
                raise errors.invalid_character(
                    f"{stat_key}[{idx}].value must be in -30..30 or null")

    for bucket_name in ("spells", "actions"):
        for bucket, entries in (character.get(bucket_name) or {}).items():
            if entries is not None and not isinstance(entries, list):
                raise errors.invalid_character(f"{bucket_name}.{bucket} must be an array or null")
            for idx, entry in enumerate(entries or []):
                if not isinstance(entry, dict):
                    raise errors.invalid_character(f"{bucket_name}.{bucket}[{idx}] must be an object")
                _optional_string(entry, "name",
                                 f"{bucket_name}.{bucket}[{idx}]")
                definition = entry.get("definition")
                if definition is not None:
                    _validate_definition(definition,
                                         f"{bucket_name}.{bucket}[{idx}].definition")
                limited = entry.get("limitedUse")
                if limited is not None and not isinstance(limited, dict):
                    raise errors.invalid_character(f"{bucket_name}.{bucket}[{idx}].limitedUse must be an object")
                if limited:
                    for key in ("maxUses", "numberUsed"):
                        _optional_bounded_integer(
                            limited, key,
                            f"{bucket_name}.{bucket}[{idx}].limitedUse")
                    _optional_integer(
                        limited, "statModifierUsesId",
                        f"{bucket_name}.{bucket}[{idx}].limitedUse")
                _optional_bool(limited or {}, "useProficiencyBonus",
                               f"{bucket_name}.{bucket}[{idx}].limitedUse")
                stat_id = limited.get("statModifierUsesId") if limited else None
                if stat_id is not None and stat_id not in range(1, 7):
                    raise errors.invalid_character(
                        f"{bucket_name}.{bucket}[{idx}].limitedUse."
                        "statModifierUsesId must be in 1..6 or null")
                for key in ("prepared", "alwaysPrepared"):
                    _optional_bool(entry, key,
                                   f"{bucket_name}.{bucket}[{idx}]")

    for idx, block in enumerate(character.get("classSpells") or []):
        if not isinstance(block, dict):
            raise errors.invalid_character(f"classSpells[{idx}] must be an object")
        entries = _optional_list(block, "spells", f"classSpells[{idx}]")
        for sidx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise errors.invalid_character(f"classSpells[{idx}].spells[{sidx}] must be an object")
            definition = entry.get("definition")
            if definition is not None:
                _validate_definition(definition,
                                     f"classSpells[{idx}].spells[{sidx}].definition")
            for key in ("prepared", "alwaysPrepared"):
                _optional_bool(entry, key,
                               f"classSpells[{idx}].spells[{sidx}]")

    for slot_key in ("spellSlots", "pactMagic"):
        seen_slot_levels = set()
        for idx, row in enumerate(character.get(slot_key) or []):
            if not isinstance(row, dict):
                raise errors.invalid_character(f"{slot_key}[{idx}] must be an object")
            for key in ("level", "available", "used"):
                if key not in row or not _integer(row.get(key)):
                    raise errors.invalid_character(
                        f"{slot_key}[{idx}].{key} must be an integer")
            if row["level"] not in range(1, 10):
                raise errors.invalid_character(
                    f"{slot_key}[{idx}].level must be in 1..9")
            if row["level"] in seen_slot_levels:
                raise errors.invalid_character(
                    f"{slot_key} contains duplicate level {row['level']}")
            seen_slot_levels.add(row["level"])
            for key in ("available", "used"):
                if abs(row[key]) > MAX_MECHANICAL_MAGNITUDE:
                    raise errors.invalid_character(
                        f"{slot_key}[{idx}].{key} exceeds the supported "
                        "numeric safety range")

    race = character.get("race") or {}
    _optional_string(race, "fullName", "race")
    if not race.get("fullName"):
        raise errors.invalid_character("race.fullName must be a non-empty string")
    _optional_string(race, "size", "race")
    _optional_integer(race, "sizeId", "race")
    speeds = _optional_dict(race, "weightSpeeds", "race")
    if speeds:
        normal = _optional_dict(speeds, "normal", "race.weightSpeeds")
        for key, value in normal.items():
            if value is not None and not _number(value):
                raise errors.invalid_character(f"race.weightSpeeds.normal.{key} must be numeric or null")
            if value is not None and not 0 <= value <= MAX_ITEM_WEIGHT:
                raise errors.invalid_character(
                    f"race.weightSpeeds.normal.{key} is outside the safety range")
    for idx, trait in enumerate(_optional_list(race, "racialTraits", "race")):
        if not isinstance(trait, dict):
            raise errors.invalid_character(f"race.racialTraits[{idx}] must be an object")
        _optional_integer(trait, "requiredLevel", f"race.racialTraits[{idx}]")
        definition = trait.get("definition")
        if definition is not None:
            _validate_definition(definition, f"race.racialTraits[{idx}].definition")

    background = character.get("background") or {}
    definition = background.get("definition")
    if definition is not None:
        _validate_definition(definition, "background.definition")

    for idx, condition in enumerate(character.get("conditions") or []):
        if not isinstance(condition, dict):
            raise errors.invalid_character(f"conditions[{idx}] must be an object")
        _optional_integer(condition, "id", f"conditions[{idx}]")
        _optional_integer(condition, "level", f"conditions[{idx}]")

    death = character.get("deathSaves") or {}
    for key in ("successCount", "failCount"):
        _optional_bounded_integer(death, key, "deathSaves")

    for key, value in (character.get("currencies") or {}).items():
        if value is not None and not _integer(value):
            raise errors.invalid_character(f"currencies.{key} must be an integer or null")
        if value is not None and abs(value) > MAX_MECHANICAL_MAGNITUDE:
            raise errors.invalid_character(
                f"currencies.{key} exceeds the supported numeric safety range")

    for idx, feat in enumerate(character.get("feats") or []):
        if not isinstance(feat, dict):
            raise errors.invalid_character(f"feats[{idx}] must be an object")
        _optional_integer(feat, "requiredLevel", f"feats[{idx}]")
        definition = feat.get("definition")
        if definition is not None:
            _validate_definition(definition, f"feats[{idx}].definition")

    for idx, custom in enumerate(character.get("customItems") or []):
        if not isinstance(custom, dict):
            raise errors.invalid_character(f"customItems[{idx}] must be an object")
        _optional_number(custom, "weight", f"customItems[{idx}]")
        if (custom.get("weight") is not None
                and not 0 <= custom["weight"] <= MAX_ITEM_WEIGHT):
            raise errors.invalid_character(
                f"customItems[{idx}].weight is outside the safety range")
        _optional_integer(custom, "quantity", f"customItems[{idx}]")
        if (custom.get("quantity") is not None
                and custom["quantity"] not in range(1, MAX_ITEM_QUANTITY + 1)):
            raise errors.invalid_character(
                f"customItems[{idx}].quantity must be in 1..{MAX_ITEM_QUANTITY} or null")
        _optional_string(custom, "name", f"customItems[{idx}]")
    _validate_container_graph(character)
    return character


def _validate_container_graph(character):
    by_id = {str(item["id"]): item for item in character.get("inventory", [])}
    character_id = str(character.get("id"))
    for item in character.get("inventory", []):
        parent = item.get("containerEntityId")
        if (parent is not None and str(parent) != character_id
                and str(parent) not in by_id):
            raise errors.invalid_character(
                "inventory container reference does not resolve in this character")
    color = {}
    for start in by_id:
        if color.get(start) == 2:
            continue
        chain = []
        current = start
        while current in by_id and current != character_id:
            state = color.get(current, 0)
            if state == 1:
                raise errors.cyclic_reference()
            if state == 2:
                break
            if len(chain) >= MAX_CONTAINER_HOPS:
                raise errors.input_limit("container traversal depth", MAX_CONTAINER_HOPS)
            color[current] = 1
            chain.append(current)
            parent = by_id[current].get("containerEntityId")
            current = str(parent) if parent is not None else None
        for item_id in chain:
            color[item_id] = 2


def _snapshot_id(envelope):
    """Hash the complete envelope except for the hash field itself."""
    material_value = copy.deepcopy(envelope)
    meta = material_value.get("meta")
    if isinstance(meta, dict):
        meta.pop("snapshot_id", None)
    material = json.dumps(material_value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(material).hexdigest()


def _valid_sha256(value):
    return bool(isinstance(value, str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", value))


def _snapshot_character(envelope):
    _validate_complexity(envelope)
    if not isinstance(envelope, dict):
        raise errors.snapshot_schema()
    if set(envelope) != {"schema", "schema_version", "meta", "source",
                         "privacy", "character"}:
        raise errors.snapshot_schema()
    if envelope.get("schema") != SNAPSHOT_SCHEMA or envelope.get("schema_version") != SNAPSHOT_VERSION:
        raise errors.snapshot_schema()
    meta = envelope.get("meta")
    source_meta = envelope.get("source")
    privacy = envelope.get("privacy")
    if not all(isinstance(value, dict) for value in (meta, source_meta, privacy)):
        raise errors.snapshot_schema()
    if set(meta) != {"engine_version", "rules_profile", "observed_at",
                     "snapshot_id", "immutable"} or meta.get("immutable") is not True:
        raise errors.snapshot_schema()
    if set(source_meta) != {"adapter", "source_id", "schema",
                            "schema_fingerprint", "normalized_data_hash",
                            "snapshot_character_hash", "coverage"}:
        raise errors.snapshot_schema()
    if set(privacy) != {"classification", "account_identifiers",
                        "linked_images", "retention", "model_transfer"}:
        raise errors.snapshot_schema()
    for field in ("engine_version", "rules_profile", "observed_at", "snapshot_id"):
        if not isinstance(meta.get(field), str) or not meta[field]:
            raise errors.snapshot_schema()
    if _parse_observed_at(meta["observed_at"]) is None:
        raise errors.snapshot_schema()
    for field in ("adapter", "source_id", "schema", "schema_fingerprint",
                  "normalized_data_hash", "snapshot_character_hash"):
        if not isinstance(source_meta.get(field), str) or not source_meta[field]:
            raise errors.snapshot_schema()
    coverage = source_meta.get("coverage")
    if (not isinstance(coverage, dict) or set(coverage) != _COVERAGE_KEYS
            or any(not isinstance(coverage[key], bool)
                   for key in SOURCE_COVERAGE_BOOLEAN_KEYS)
            or not isinstance(coverage[SOURCE_COVERAGE_SCOPE_KEY], list)
            or any(not isinstance(family, str)
                   for family in coverage[SOURCE_COVERAGE_SCOPE_KEY])
            or coverage[SOURCE_COVERAGE_SCOPE_KEY] != sorted(set(
                coverage[SOURCE_COVERAGE_SCOPE_KEY]))
            or any(family not in source_field_registry.FAMILIES
                   for family in coverage[SOURCE_COVERAGE_SCOPE_KEY])):
        raise errors.snapshot_schema()
    if (meta["rules_profile"] != RULES_PROFILE
            or source_meta["schema"] != SOURCE_SCHEMA
            or source_meta["schema_fingerprint"] != SOURCE_SCHEMA_FINGERPRINT
            or not _valid_sha256(source_meta["normalized_data_hash"])
            or not _valid_sha256(source_meta["snapshot_character_hash"])
            or not _valid_sha256(meta["snapshot_id"])):
        # Schema/rules changes require an explicit migration rather than being
        # silently interpreted by an older engine.
        raise errors.snapshot_schema()
    if (privacy.get("classification") not in {"mechanical", "mechanical+persona"}
            or privacy.get("account_identifiers") != "omitted"
            or privacy.get("linked_images") != "omitted"
            or privacy.get("retention") != "caller-controlled local artifact"
            or privacy.get("model_transfer") != "not implied by snapshot creation"):
        raise errors.snapshot_schema()
    if source_meta["source_id"] != "local" and not _valid_id(source_meta["source_id"]):
        raise errors.snapshot_schema()
    character = envelope.get("character")
    validate_character(character)
    if (source_meta["source_id"] != "local"
            and source_meta["source_id"] != str(character.get("id"))):
        raise errors.snapshot_integrity()
    include_persona = privacy["classification"] == "mechanical+persona"
    if privacy_filter(character, include_persona=include_persona) != character:
        raise errors.snapshot_integrity()
    expected_hash = source_meta["snapshot_character_hash"]
    actual_hash = normalized_hash(character)
    if expected_hash != actual_hash:
        raise errors.snapshot_integrity()
    if source_meta["normalized_data_hash"] != mechanical_hash(character):
        raise errors.snapshot_integrity()
    expected_snapshot_id = _snapshot_id(envelope)
    if meta["snapshot_id"] != expected_snapshot_id:
        raise errors.snapshot_integrity()
    return character


def _extract_character(envelope):
    if not isinstance(envelope, dict):
        raise errors.invalid_character("top-level JSON must be an object")
    if envelope.get("schema") == SNAPSHOT_SCHEMA:
        return _snapshot_character(envelope), envelope
    character = envelope.get("data", envelope)
    validate_character(character)
    return character, None


def load(ref, *, allow_local=True, timeout=30):
    """Load and validate a local, remote, or snapshot character source."""
    kind, value = parse_ref(ref, allow_local=allow_local)
    observed_at = _now()
    if kind == "path":
        try:
            with value.open("rb") as stream:
                raw = _bounded_read(stream, limit=MAX_SNAPSHOT_BYTES)
                envelope = _decode_json(raw, "local JSON")
        except OSError as exc:
            raise errors.file_read(str(exc))
        if (len(raw) > MAX_INPUT_BYTES
                and (not isinstance(envelope, dict)
                     or envelope.get("schema") != SNAPSHOT_SCHEMA)):
            raise errors.input_too_large(MAX_INPUT_BYTES)
        character, snapshot = _extract_character(envelope)
        if snapshot:
            source = snapshot.get("source") or {}
            meta = snapshot.get("meta") or {}
            return LoadedCharacter(
                copy.deepcopy(character),
                source.get("adapter") or "snapshot",
                _safe_source_id(source.get("source_id")),
                meta.get("observed_at") or observed_at,
                source.get("schema") or SOURCE_SCHEMA,
                source.get("schema_fingerprint") or SOURCE_SCHEMA_FINGERPRINT,
                source.get("normalized_data_hash"),
                copy.deepcopy(source.get("coverage")),
            )
        mechanical_character, coverage = privacy_filter_with_coverage(character)
        return LoadedCharacter(
            copy.deepcopy(character), "local-json",
            _safe_source_id(character.get("id")), observed_at,
            source_revision=normalized_hash(mechanical_character),
            source_coverage=coverage)

    character_id = value
    url = ("https://character-service.dndbeyond.com/character/v5/character/"
           + character_id)
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "charactercheck (+https://github.com/chaoz23/charactercheck)",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            envelope = _decode_json(_bounded_read(response), "D&D Beyond response")
    except urllib.error.HTTPError as exc:
        if getattr(exc, "fp", None) is not None:
            exc.close()
        if exc.code == 403:
            raise errors.not_public(ref)
        if exc.code == 404:
            raise errors.not_found(ref)
        if exc.code == 429:
            raise errors.rate_limited(ref)
        raise errors.upstream(ref, exc.code)
    except urllib.error.URLError as exc:
        raise errors.network(ref, str(getattr(exc, "reason", exc)))
    except (OSError, socket.timeout, TimeoutError, http.client.HTTPException) as exc:
        raise errors.network(ref, str(exc))
    if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), dict):
        raise errors.bad_json(ref, "remote response has no 'data' object")
    character = envelope["data"]
    validate_character(character)
    if str(character.get("id")) != character_id:
        raise errors.invalid_character("response character id does not match the requested id")
    mechanical_character, coverage = privacy_filter_with_coverage(character)
    return LoadedCharacter(
        copy.deepcopy(character), "ddb-character-service-v5",
        character_id, observed_at,
        source_revision=normalized_hash(mechanical_character),
        source_coverage=coverage)


def normalized_hash(character):
    body = json.dumps(character, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(body).hexdigest()


_MECHANICAL_TOP_LEVEL = {
    "id", "name", "stats", "overrideStats", "bonusStats", "classes",
    "inventory", "modifiers", "characterValues", "race", "background",
    "spells", "classSpells", "actions", "baseHitPoints", "bonusHitPoints",
    "overrideHitPoints", "removedHitPoints", "temporaryHitPoints",
    "currentXp", "alignmentId", "inspiration", "conditions", "feats",
    "spellSlots", "pactMagic", "currencies", "deathSaves", "customItems",
    "preferences",
}
_SAFE_PREFERENCE_KEYS = {
    "enableOptionalClassFeatures", "enableOptionalOrigins", "encumbranceType",
    "enforceFeatRules", "enforceMulticlassRules", "hitPointType",
    "ignoreCoinWeight", "longRestType", "progressionType", "useHomebrewContent",
}
_ALWAYS_PRIVATE_KEYS = {
    "username", "userid", "accountid", "campaignid", "notes", "gender",
    "socialname", "faith", "lifestyle", "backstory", "organizations",
    "organization", "allies", "enemies", "otherholdings", "othernotes",
    "personalpossessions", "appearance", "campaign", "campaignsetting",
    "readonlyurl", "providedfrom", "decorations",
    "age", "height", "weight", "hair", "skin", "eyes",
}
_PROSE_KEYS = {
    "description", "shortdescription", "longdescription", "snippet",
    "flavortext", "biography",
}
_PRIVATE_KEY_PARTS = ("avatar", "portrait", "imageurl", "image_url")

_SNAPSHOT_BUCKETS = {
    "race", "class", "background", "feat", "condition", "item",
    "_unclassified",
}
_DEFINITION_KEYS = {
    "id", "name", "armorClass", "armorTypeId", "attackType",
    "bundleSize", "spellCastingAbilityId", "hitDice", "requiredLevel",
    "level", "weight", "canAttune", "canEquip", "isConsumable",
    "isContainer", "magic", "damageType", "damage", "grantedModifiers",
    "properties", "classFeatures", "_semanticGaps",
}
_MODIFIER_KEYS = {
    "type", "subType", "restriction", "value", "statId", "componentId",
    "isGranted",
}
_KNOWN_CHARACTER_VALUE_TYPES = {
    1, 2, 3, 8, 9, 24, 25, 26, 27, 28, 29, 39, 40, 41,
}
SOURCE_COVERAGE_BOOLEAN_KEYS = (
    "unclassified_top_level_omitted",
    "unclassified_nested_omitted",
    "semantic_values_omitted",
)
SOURCE_COVERAGE_SCOPE_KEY = "scoped_mechanical_omissions"
SOURCE_COVERAGE_KEYS = SOURCE_COVERAGE_BOOLEAN_KEYS + (
    SOURCE_COVERAGE_SCOPE_KEY,)
_COVERAGE_KEYS = set(SOURCE_COVERAGE_KEYS)


def empty_source_coverage():
    coverage = {key: False for key in SOURCE_COVERAGE_BOOLEAN_KEYS}
    coverage[SOURCE_COVERAGE_SCOPE_KEY] = set()
    return coverage


def normalize_source_coverage(*values):
    """Merge typed omission signals without retaining source field names."""
    coverage = empty_source_coverage()
    for value in values:
        value = value or {}
        for key in SOURCE_COVERAGE_BOOLEAN_KEYS:
            coverage[key] = coverage[key] or bool(value.get(key))
        families = value.get(SOURCE_COVERAGE_SCOPE_KEY) or []
        if isinstance(families, (list, tuple, set, frozenset)):
            for family in families:
                if (isinstance(family, str)
                        and family in source_field_registry.FAMILIES):
                    coverage[SOURCE_COVERAGE_SCOPE_KEY].add(family)
                else:
                    coverage["unclassified_nested_omitted"] = True
        else:
            coverage["unclassified_nested_omitted"] = True
    coverage[SOURCE_COVERAGE_SCOPE_KEY] = sorted(
        coverage[SOURCE_COVERAGE_SCOPE_KEY])
    return coverage


def safe_mechanical_label(value, *, limit=256):
    """Bound a known player-authored mechanical label without reinterpreting it."""
    if not isinstance(value, str):
        return value
    text = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _privacy_key(key):
    normalized = str(key).lower().replace("-", "").replace("_", "")
    return (normalized in _ALWAYS_PRIVATE_KEYS
            or normalized in _PROSE_KEYS
            or any(part.replace("_", "") in normalized
                   for part in _PRIVATE_KEY_PARTS))


def _closed_object(value, allowed, coverage, *, path, top_level=False,
                   ignored=()):
    """Copy declared keys and route omissions without retaining their names."""
    out = {}
    ignored = set(ignored)
    for key, child in value.items():
        if key in allowed:
            out[key] = copy.deepcopy(child)
        elif key in ignored or _privacy_key(key):
            continue
        else:
            scope = source_field_registry.omission_scope(path, key)
            if scope is not None:
                # Empty optional containers and false/absent feature flags do
                # not contain an omitted mechanic. Zero remains meaningful.
                empty_optional = (child is None or child is False
                                  or child == "" or child == [] or child == {})
                if not empty_optional:
                    coverage[SOURCE_COVERAGE_SCOPE_KEY].update(scope)
                continue
            coverage[("unclassified_top_level_omitted" if top_level else
                      "unclassified_nested_omitted")] = True
    return out


def _closed_list(value, sanitizer, coverage, path):
    if value is None:
        return None
    if not isinstance(value, list):
        coverage["unclassified_nested_omitted"] = True
        return None
    if any(not isinstance(child, dict) for child in value):
        coverage["unclassified_nested_omitted"] = True
    return [sanitizer(child, coverage, path) for child in value
            if isinstance(child, dict)]


def _sanitize_modifier(value, coverage, path):
    out = _closed_object(
        value, _MODIFIER_KEYS, coverage,
        path=path,
        ignored=(source_field_registry.MODIFIER_METADATA_KEYS
                 | source_field_registry.MODIFIER_SEMANTIC_KEYS))
    omitted_semantics = {
        key for key in source_field_registry.MODIFIER_SEMANTIC_KEYS
        if key in value and value[key] not in (None, False, "", [], {})
    }
    if omitted_semantics:
        spec = semantic_registry.handler_for(value)
        scope = (spec.affects if spec is not None
                 else source_field_registry.modifier_scope(value))
        if scope is None:
            coverage["unclassified_nested_omitted"] = True
        else:
            coverage[SOURCE_COVERAGE_SCOPE_KEY].update(scope)
    for key in ("type", "subType"):
        identifier = out.get(key)
        if (identifier is not None
                and (not isinstance(identifier, str)
                     or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}",
                                         identifier))):
            out[key] = "unclassified"
            coverage["unclassified_nested_omitted"] = True
    restriction = out.get("restriction")
    if isinstance(restriction, str) and restriction:
        # Its presence changes whether a handler can be applied, while its
        # player/source-authored prose must not cross the snapshot boundary.
        out["restriction"] = "present; source text omitted"
    return out


def _sanitize_feature(value, coverage, path):
    out = _closed_object(
        value, {"definition", "requiredLevel"}, coverage, path=path)
    if isinstance(out.get("definition"), dict):
        out["definition"] = _sanitize_definition(
            out["definition"], coverage, path + ".definition")
    return out


def _sanitize_definition(value, coverage, path, *, inventory_item=False):
    out = _closed_object(value, _DEFINITION_KEYS, coverage, path=path)
    gaps = set(out.get("_semanticGaps") or [])
    if isinstance(out.get("damage"), dict):
        out["damage"] = _closed_object(
            out["damage"],
            {"diceString", "diceCount", "diceValue", "diceMultiplier",
             "fixedValue"}, coverage, path=path + ".damage")
        canonical = canonical_damage_dice(out["damage"])
        if out["damage"].get("diceString") is not None:
            if (canonical is None
                    or int(canonical.split("d", 1)[1])
                    not in KNOWN_DDB_DAMAGE_DIE_VALUES):
                # Preserve only the fact that unsupported syntax existed. Raw
                # formula-like strings are untrusted content and must not cross
                # the agent/snapshot boundary.
                out["damage"]["diceString"] = None
                gaps.add("damage_dice")
                coverage["semantic_values_omitted"] = True
            else:
                # Reconstruct from integers so only inert syntax can cross.
                out["damage"]["diceString"] = canonical
        elif any(out["damage"].get(key) is not None
                 for key in ("diceCount", "diceValue")):
            gaps.add("damage_dice")
        if (out["damage"].get("diceMultiplier") is not None
                or out["damage"].get("fixedValue") is not None):
            gaps.add("additional_damage_semantics")
    damage_type = out.get("damageType")
    if damage_type is not None and damage_type not in KNOWN_DDB_DAMAGE_TYPES:
        out["damageType"] = None
        gaps.add("damage_type")
        coverage["semantic_values_omitted"] = True
    if isinstance(out.get("properties"), list):
        properties = []
        for prop in out["properties"]:
            if not isinstance(prop, dict):
                coverage["unclassified_nested_omitted"] = True
                continue
            if any(isinstance(prop.get(key), str) and prop[key].strip()
                   for key in ("notes", "description")):
                # DDB uses property notes for mechanics such as Versatile's
                # alternate damage. Preserve presence, never prose.
                gaps.add("weapon_property")
                coverage["semantic_values_omitted"] = True
            clean = _closed_object(
                prop, {"id", "name"}, coverage,
                path=path + ".properties[]")
            identifier = clean.get("id")
            name = clean.get("name")
            canonical = (ddb_registry.WEAPON_PROPERTIES.get(identifier)
                         if isinstance(identifier, int)
                         and not isinstance(identifier, bool) else None)
            if canonical is not None:
                if name != canonical:
                    gaps.add("weapon_property")
                    coverage["semantic_values_omitted"] = True
                properties.append({"id": identifier, "name": canonical})
            elif identifier is None and name in _WEAPON_PROPERTY_ID_BY_NAME:
                # Legacy/synthetic name-only inputs remain readable, but their
                # weaker adapter evidence cannot earn trusted weapon semantics.
                properties.append({
                    "id": _WEAPON_PROPERTY_ID_BY_NAME[name],
                    "name": name,
                })
                gaps.add("weapon_property")
            else:
                # Retain only a bounded numeric identifier when available.
                # Arbitrary property text never crosses the boundary.
                if isinstance(identifier, int) and not isinstance(identifier, bool):
                    properties.append({"id": identifier,
                                       "name": "unclassified"})
                gaps.add("weapon_property")
                coverage["semantic_values_omitted"] = True
        out["properties"] = properties
    if inventory_item:
        armor_type = out.get("armorTypeId")
        armor_class = out.get("armorClass")
        if ((armor_type is not None or armor_class is not None)
                and (armor_type not in KNOWN_DDB_ARMOR_TYPE_IDS
                     or not isinstance(armor_class, int)
                     or isinstance(armor_class, bool)
                     or armor_class < 1)):
            gaps.add("armor_type")
        damage = out.get("damage") or {}
        if damage.get("diceString"):
            if out.get("attackType") not in KNOWN_DDB_ATTACK_TYPE_IDS:
                gaps.add("attack_type")
            if out.get("damageType") not in KNOWN_DDB_DAMAGE_TYPES:
                gaps.add("damage_type")
    if gaps:
        out["_semanticGaps"] = sorted(gaps)
    else:
        out.pop("_semanticGaps", None)
    if isinstance(out.get("grantedModifiers"), list):
        out["grantedModifiers"] = [
            _sanitize_modifier(modifier, coverage,
                               path + ".grantedModifiers[]")
            for modifier in out["grantedModifiers"]
            if isinstance(modifier, dict)
        ]
    if "classFeatures" in out:
        out["classFeatures"] = _closed_list(
            out["classFeatures"], _sanitize_feature, coverage,
            path + ".classFeatures[]")
    return out


def _sanitize_stat(value, coverage, path):
    return _closed_object(value, {"id", "value"}, coverage, path=path)


def _sanitize_class(value, coverage, path):
    out = _closed_object(
        value,
        {"level", "hitDiceUsed", "definition", "subclassDefinition",
         "classFeatures"},
        coverage, path=path,
    )
    for key in ("definition", "subclassDefinition"):
        if isinstance(out.get(key), dict):
            out[key] = _sanitize_definition(
                out[key], coverage, path + f".{key}")
    if "classFeatures" in out:
        out["classFeatures"] = _closed_list(
            out["classFeatures"], _sanitize_feature, coverage,
            path + ".classFeatures[]")
    return out


def _sanitize_inventory_item(value, coverage, path):
    out = _closed_object(
        value,
        {"id", "containerEntityId", "equipped", "isAttuned", "quantity",
         "definition"},
        coverage, path=path,
    )
    if isinstance(out.get("definition"), dict):
        out["definition"] = _sanitize_definition(
            out["definition"], coverage, path + ".definition",
            inventory_item=True)
    return out


def _sanitize_buckets(value, sanitizer, coverage, path):
    out = {}
    for bucket, entries in value.items():
        safe_bucket = bucket if bucket in _SNAPSHOT_BUCKETS else "_unclassified"
        if safe_bucket != bucket:
            coverage["unclassified_nested_omitted"] = True
        if entries is None:
            out.setdefault(safe_bucket, None)
            continue
        if not isinstance(entries, list):
            coverage["unclassified_nested_omitted"] = True
            continue
        target = out.setdefault(safe_bucket, [])
        if target is None:
            target = out[safe_bucket] = []
        target.extend(sanitizer(entry, coverage, path + "[]")
                      for entry in entries if isinstance(entry, dict))
    return out


def _sanitize_character_value(value, coverage, path):
    out = _closed_object(
        value, {"typeId", "valueId", "value"}, coverage, path=path)
    type_id = out.get("typeId")
    if type_id not in _KNOWN_CHARACTER_VALUE_TYPES:
        # Preserve the existence and numeric handler id so the registry stays
        # fail-closed, but never retain arbitrary unknown payload strings.
        coverage["unclassified_nested_omitted"] = True
        return {
            "typeId": type_id if isinstance(type_id, int)
            and not isinstance(type_id, bool) else None,
            "valueId": None,
            "value": None,
        }
    if type_id == 9:
        # Preserve existence/validity so malformed known data still fails
        # closed, but never retain the custom note itself.
        out["value"] = ("source text omitted"
                        if isinstance(out.get("value"), str) else None)
        return out
    if type_id == 8:
        label = out.get("value")
        if not isinstance(label, str):
            out["value"] = None
            return out
        out["value"] = safe_mechanical_label(label)
        return out
    if type_id in (28, 29):
        if not (isinstance(out.get("value"), bool)
                or out.get("value") in ("True", "False")):
            out["value"] = "invalid"
        return out
    # Known numeric/boolean handlers need malformed input to remain invalid,
    # but malformed free text itself is neither mechanical nor safe to retain.
    raw = out.get("value")
    if isinstance(raw, str) and not re.fullmatch(r"[+-]?[0-9]+", raw.strip()):
        out["value"] = "invalid"
    elif not isinstance(raw, (int, float, str, bool, type(None))):
        out["value"] = None
    return out


def _sanitize_spell_entry(value, coverage, path):
    out = _closed_object(
        value, {"definition", "prepared", "alwaysPrepared", "limitedUse"},
        coverage, path=path)
    if isinstance(out.get("definition"), dict):
        out["definition"] = _sanitize_definition(
            out["definition"], coverage, path + ".definition")
    if isinstance(out.get("limitedUse"), dict):
        out["limitedUse"] = _closed_object(
            out["limitedUse"],
            {"maxUses", "statModifierUsesId", "numberUsed",
             "useProficiencyBonus"}, coverage, path=path + ".limitedUse")
    return out


def _sanitize_action(value, coverage, path):
    out = _closed_object(
        value, {"name", "definition", "limitedUse"}, coverage, path=path)
    if isinstance(out.get("definition"), dict):
        out["definition"] = _sanitize_definition(
            out["definition"], coverage, path + ".definition")
    if isinstance(out.get("limitedUse"), dict):
        out["limitedUse"] = _closed_object(
            out["limitedUse"],
            {"maxUses", "statModifierUsesId", "numberUsed",
             "useProficiencyBonus"}, coverage, path=path + ".limitedUse")
    return out


def _privacy_filter_with_coverage(character, *, include_persona=False):
    coverage = empty_source_coverage()
    value = _closed_object(
        character, _MECHANICAL_TOP_LEVEL, coverage, top_level=True,
        ignored={"traits"}, path="$",
    )

    for key in ("stats", "overrideStats", "bonusStats"):
        if isinstance(value.get(key), list):
            value[key] = [_sanitize_stat(row, coverage, key + "[]")
                          for row in value[key] if isinstance(row, dict)]
    if isinstance(value.get("classes"), list):
        value["classes"] = [
            _sanitize_class(row, coverage, "classes[]")
            for row in value["classes"] if isinstance(row, dict)
        ]
    if isinstance(value.get("inventory"), list):
        value["inventory"] = [
            _sanitize_inventory_item(row, coverage, "inventory[]")
            for row in value["inventory"] if isinstance(row, dict)
        ]
    if isinstance(value.get("modifiers"), dict):
        value["modifiers"] = _sanitize_buckets(
            value["modifiers"], _sanitize_modifier, coverage, "modifiers")

    filtered_values = []
    for record in value.get("characterValues") or []:
        if not isinstance(record, dict):
            continue
        filtered = _sanitize_character_value(
            record, coverage, "characterValues[]")
        if filtered is not None:
            filtered_values.append(filtered)
    if "characterValues" in value:
        value["characterValues"] = filtered_values

    if isinstance(value.get("race"), dict):
        race = _closed_object(
            value["race"],
            {"fullName", "size", "sizeId", "weightSpeeds", "racialTraits"},
            coverage, path="race")
        if isinstance(race.get("weightSpeeds"), dict):
            speeds = _closed_object(
                race["weightSpeeds"], {"normal"}, coverage,
                path="race.weightSpeeds")
            if isinstance(speeds.get("normal"), dict):
                speeds["normal"] = _closed_object(
                    speeds["normal"],
                    {"walk", "fly", "swim", "climb", "burrow"}, coverage,
                    path="race.weightSpeeds.normal")
            race["weightSpeeds"] = speeds
        if isinstance(race.get("racialTraits"), list):
            race["racialTraits"] = [
                _sanitize_feature(row, coverage, "race.racialTraits[]")
                for row in race["racialTraits"] if isinstance(row, dict)
            ]
        value["race"] = race

    if isinstance(value.get("background"), dict):
        background = _closed_object(
            value["background"], {"definition"}, coverage,
            path="background")
        if isinstance(background.get("definition"), dict):
            background["definition"] = _sanitize_definition(
                background["definition"], coverage, "background.definition")
        value["background"] = background

    for key in ("spells",):
        if isinstance(value.get(key), dict):
            value[key] = _sanitize_buckets(
                value[key], _sanitize_spell_entry, coverage, key)
    if isinstance(value.get("actions"), dict):
        value["actions"] = _sanitize_buckets(
            value["actions"], _sanitize_action, coverage, "actions")

    if isinstance(value.get("classSpells"), list):
        blocks = []
        for block in value["classSpells"]:
            if not isinstance(block, dict):
                continue
            clean = _closed_object(
                block, {"spells"}, coverage, path="classSpells[]")
            if isinstance(clean.get("spells"), list):
                clean["spells"] = [
                    _sanitize_spell_entry(row, coverage, "classSpells[].spells[]")
                    for row in clean["spells"] if isinstance(row, dict)
                ]
            blocks.append(clean)
        value["classSpells"] = blocks

    if isinstance(value.get("feats"), list):
        value["feats"] = [
            _sanitize_feature(row, coverage, "feats[]")
            for row in value["feats"] if isinstance(row, dict)
        ]
    if isinstance(value.get("conditions"), list):
        value["conditions"] = [
            _closed_object(
                row, {"id", "level"}, coverage, path="conditions[]")
            for row in value["conditions"] if isinstance(row, dict)
        ]
    for key in ("spellSlots", "pactMagic"):
        if isinstance(value.get(key), list):
            value[key] = [
                _closed_object(
                    row, {"level", "available", "used"}, coverage,
                    path=key + "[]")
                for row in value[key] if isinstance(row, dict)
            ]
    if isinstance(value.get("deathSaves"), dict):
        value["deathSaves"] = _closed_object(
            value["deathSaves"], {"successCount", "failCount"}, coverage,
            path="deathSaves")
    if isinstance(value.get("currencies"), dict):
        value["currencies"] = _closed_object(
            value["currencies"], {"cp", "sp", "ep", "gp", "pp"}, coverage,
            path="currencies")
    if isinstance(value.get("customItems"), list):
        customs = []
        for index, custom in enumerate(value["customItems"], 1):
            if not isinstance(custom, dict):
                continue
            clean = _closed_object(
                custom, {"name", "weight", "quantity"}, coverage,
                path="customItems[]")
            if "name" in clean:
                clean["name"] = f"Custom item {index}"
            customs.append(clean)
        value["customItems"] = customs
    if isinstance(value.get("preferences"), dict):
        value["preferences"] = _closed_object(
            value["preferences"], _SAFE_PREFERENCE_KEYS, coverage,
            path="preferences")
        for key, preference in list(value["preferences"].items()):
            if not isinstance(preference, (int, bool, type(None))):
                value["preferences"][key] = None
                coverage["unclassified_nested_omitted"] = True

    if include_persona:
        traits = character.get("traits")
        if isinstance(traits, dict):
            allowed = ("personalityTraits", "ideals", "bonds", "flaws")
            persona = {}
            remaining = 12_000
            for key in allowed:
                text = traits.get(key)
                if not isinstance(text, str) or not text or remaining <= 0:
                    continue
                bounded = text[:min(4_000, remaining)]
                persona[key] = bounded
                remaining -= len(bounded)
            value["traits"] = persona
    return value, coverage


def privacy_filter(character, *, include_persona=False):
    """Return a copy suitable for an explicit snapshot export.

    Account identifiers, linked imagery, notes, and appearance are always
    omitted. The four bounded persona fields require explicit local opt-in.
    """
    return _privacy_filter_with_coverage(
        character, include_persona=include_persona)[0]


def privacy_filter_with_coverage(character, *, include_persona=False):
    """Return the public projection and its closed schema-drift signal.

    Coverage deliberately reveals neither omitted field names nor values. The
    scoped list contains canonical mechanical family names only. Callers that
    publish trust assessments must propagate it: silently discarding an
    omission could turn incomplete observation into apparent trust.
    """
    character, coverage = _privacy_filter_with_coverage(
        character, include_persona=include_persona)
    return character, normalize_source_coverage(coverage)


def mechanical_hash(character):
    """Hash only the default mechanical projection exposed to callers."""
    return normalized_hash(privacy_filter(character, include_persona=False))


@dataclass(frozen=True)
class CharacterSnapshotV1:
    """Deeply immutable snapshot represented internally as canonical JSON."""

    _canonical_json: str

    @classmethod
    def from_dict(cls, envelope):
        _snapshot_character(envelope)
        canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False)
        return cls(canonical)

    def to_dict(self):
        return json.loads(self._canonical_json)

    def character(self):
        return self.to_dict()["character"]

    @property
    def revision(self):
        return self.to_dict()["source"]["normalized_data_hash"]

    @property
    def snapshot_id(self):
        return self.to_dict()["meta"]["snapshot_id"]


def make_snapshot_object(loaded, *, include_persona=False):
    """Create an immutable snapshot from a single already-completed load."""
    from . import __version__  # runtime import avoids package-init cycle

    character, coverage = privacy_filter_with_coverage(
        loaded.character, include_persona=include_persona)
    coverage = normalize_source_coverage(coverage, loaded.source_coverage)
    mechanical_character = privacy_filter(
        loaded.character, include_persona=False)
    character_hash = normalized_hash(character)
    revision = normalized_hash(mechanical_character)
    envelope = {
        "schema": SNAPSHOT_SCHEMA,
        "schema_version": SNAPSHOT_VERSION,
        "meta": {
            "engine_version": __version__,
            "rules_profile": RULES_PROFILE,
            "observed_at": loaded.observed_at,
            "snapshot_id": "sha256:" + "0" * 64,
            "immutable": True,
        },
        "source": {
            "adapter": loaded.adapter,
            "source_id": loaded.source_id,
            "schema": loaded.source_schema,
            "schema_fingerprint": loaded.source_schema_fingerprint,
            "normalized_data_hash": revision,
            "snapshot_character_hash": character_hash,
            "coverage": coverage,
        },
        "privacy": {
            "classification": "mechanical+persona" if include_persona else "mechanical",
            "account_identifiers": "omitted",
            "linked_images": "omitted",
            "retention": "caller-controlled local artifact",
            "model_transfer": "not implied by snapshot creation",
        },
        "character": character,
    }
    envelope["meta"]["snapshot_id"] = _snapshot_id(envelope)
    return CharacterSnapshotV1.from_dict(envelope)


def make_snapshot(loaded, *, include_persona=False):
    """Serialize a CharacterSnapshotV1 for JSON-facing compatibility."""
    return make_snapshot_object(loaded, include_persona=include_persona).to_dict()


def load_snapshot(ref):
    """Load a path and require that it contain CharacterSnapshotV1."""
    kind, path = parse_ref(ref, allow_local=True)
    if kind != "path":
        raise errors.snapshot_required()
    try:
        with path.open("rb") as stream:
            envelope = _decode_json(
                _bounded_read(stream, limit=MAX_SNAPSHOT_BYTES), "snapshot")
    except OSError as exc:
        raise errors.file_read(str(exc))
    return CharacterSnapshotV1.from_dict(envelope).to_dict()


def snapshot_character(envelope):
    """Validate a snapshot object and return an isolated character copy."""
    return copy.deepcopy(_snapshot_character(envelope))
