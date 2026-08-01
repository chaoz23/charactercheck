"""Purpose-limited, pinned D&D Beyond adapter facts.

This module intentionally does not contact D&D Beyond.  It validates and
loads the bundled registry artifact, exposes immutable ID-to-name lookups, and
computes a semantic fingerprint over the minimal tables used by current
evaluator branches. It is deliberately not a full DDB configuration mirror.

The initial facts were independently observed from D&D Beyond's config JSON
and the allowlisted subset was cross-checked against MrPrimate/ddb-importer's
MIT-licensed fallback config. Full source and attribution metadata live beside
the tables in ``ddb-config-registry.json``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from importlib import resources
import json
import os
import re
from types import MappingProxyType
from typing import Any, Optional, Union


REGISTRY_RESOURCE = "ddb-config-registry.json"
REGISTRY_SCHEMA_VERSION = "charactercheck.ddb-config-registry/1"
_LOOKUP_TABLES = (
    "armor_types",
    "range_types",
    "damage_types",
    "weapon_properties",
)
_TABLE_KEYS = (*_LOOKUP_TABLES, "dice_values")
_ROOT_KEYS = frozenset(("schema_version", "metadata", "tables"))
_METADATA_KEYS = frozenset((
    "source_url",
    "observed_at",
    "source_last_modified",
    "source_access",
    "source_body_sha256",
    "semantic_fingerprint_sha256",
    "cross_check",
    "attribution",
))
_CROSS_CHECK_KEYS = frozenset((
    "repository_url",
    "commit",
    "file_path",
    "file_sha256",
    "license",
    "license_url",
    "allowlisted_subset_match",
))
_ATTRIBUTION_KEYS = frozenset((
    "statement",
    "upstream",
    "cross_check_project",
    "copyright",
))
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class DDBRegistryError(ValueError):
    """The bundled or supplied DDB registry is unsafe to use."""


@dataclass(frozen=True)
class DDBRegistry:
    """Validated immutable DDB semantic registry."""

    schema_version: str
    metadata: Mapping
    tables: Mapping
    fingerprint: str

    @property
    def armor_types(self) -> Mapping:
        return self.tables["armor_types"]

    @property
    def range_types(self) -> Mapping:
        return self.tables["range_types"]

    @property
    def damage_types(self) -> Mapping:
        return self.tables["damage_types"]

    @property
    def weapon_properties(self) -> Mapping:
        return self.tables["weapon_properties"]

    @property
    def dice_values(self) -> tuple:
        return self.tables["dice_values"]

    def lookup(self, table: str, identifier: int) -> Optional[str]:
        """Return a known label, preserving unknown IDs as ``None``.

        Table names are intentionally explicit rather than normalized or
        aliased.  A boolean is rejected even though Python considers it an
        integer, because ``True`` must never silently resolve to DDB ID 1.
        """

        if table not in _LOOKUP_TABLES:
            raise KeyError(f"not an ID lookup table: {table!r}")
        if type(identifier) is not int:
            raise TypeError("DDB registry identifiers must be integers")
        return self.tables[table].get(identifier)


def _duplicate_safe_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DDBRegistryError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _exact_keys(value: Any, expected, label: str) -> None:
    if not isinstance(value, Mapping):
        raise DDBRegistryError(f"{label} must be an object")
    actual = frozenset(value)
    if actual != frozenset(expected):
        missing = sorted(frozenset(expected) - actual)
        extra = sorted(actual - frozenset(expected))
        raise DDBRegistryError(
            f"{label} has invalid keys; missing={missing}, extra={extra}")


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DDBRegistryError(f"{label} must be a non-empty trimmed string")
    return value


def _hash_string(value: Any, label: str) -> str:
    value = _nonempty_string(value, label)
    if not _SHA256.fullmatch(value):
        raise DDBRegistryError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _validate_metadata(metadata: Any) -> None:
    _exact_keys(metadata, _METADATA_KEYS, "metadata")
    source_url = _nonempty_string(metadata["source_url"],
                                  "metadata.source_url")
    if not source_url.startswith("https://"):
        raise DDBRegistryError("metadata.source_url must use HTTPS")
    observed_at = _nonempty_string(metadata["observed_at"],
                                   "metadata.observed_at")
    if not _UTC_TIMESTAMP.fullmatch(observed_at):
        raise DDBRegistryError(
            "metadata.observed_at must be a whole-second UTC timestamp")
    _nonempty_string(metadata["source_last_modified"],
                     "metadata.source_last_modified")
    _nonempty_string(metadata["source_access"], "metadata.source_access")
    _hash_string(metadata["source_body_sha256"],
                 "metadata.source_body_sha256")
    _hash_string(metadata["semantic_fingerprint_sha256"],
                 "metadata.semantic_fingerprint_sha256")

    cross_check = metadata["cross_check"]
    _exact_keys(cross_check, _CROSS_CHECK_KEYS, "metadata.cross_check")
    for key in ("repository_url", "file_path", "license", "license_url"):
        _nonempty_string(cross_check[key], f"metadata.cross_check.{key}")
    if not cross_check["repository_url"].startswith("https://"):
        raise DDBRegistryError(
            "metadata.cross_check.repository_url must use HTTPS")
    if not cross_check["license_url"].startswith("https://"):
        raise DDBRegistryError(
            "metadata.cross_check.license_url must use HTTPS")
    commit = _nonempty_string(cross_check["commit"],
                              "metadata.cross_check.commit")
    if not _COMMIT.fullmatch(commit):
        raise DDBRegistryError(
            "metadata.cross_check.commit must be a full lowercase git SHA")
    _hash_string(cross_check["file_sha256"],
                 "metadata.cross_check.file_sha256")
    if cross_check["allowlisted_subset_match"] is not True:
        raise DDBRegistryError(
            "metadata.cross_check.allowlisted_subset_match must be true")

    attribution = metadata["attribution"]
    _exact_keys(attribution, _ATTRIBUTION_KEYS, "metadata.attribution")
    for key in ("statement", "upstream", "cross_check_project"):
        _nonempty_string(attribution[key], f"metadata.attribution.{key}")
    copyright_lines = attribution["copyright"]
    if (not isinstance(copyright_lines, list) or not copyright_lines
            or any(not isinstance(line, str) or not line.strip()
                   for line in copyright_lines)):
        raise DDBRegistryError(
            "metadata.attribution.copyright must be non-empty strings")


def _validate_named_table(value: Any, label: str):
    if not isinstance(value, list) or not value:
        raise DDBRegistryError(f"tables.{label} must be a non-empty array")
    normalized = []
    seen_ids = set()
    previous_id = None
    for index, entry in enumerate(value):
        entry_label = f"tables.{label}[{index}]"
        _exact_keys(entry, ("id", "name"), entry_label)
        identifier = entry["id"]
        if type(identifier) is not int or identifier <= 0:
            raise DDBRegistryError(
                f"{entry_label}.id must be a positive integer")
        if identifier in seen_ids:
            raise DDBRegistryError(
                f"tables.{label} contains duplicate id {identifier}")
        if previous_id is not None and identifier <= previous_id:
            raise DDBRegistryError(
                f"tables.{label} must be strictly sorted by id")
        seen_ids.add(identifier)
        previous_id = identifier
        normalized.append({
            "id": identifier,
            "name": _nonempty_string(entry["name"],
                                     f"{entry_label}.name"),
        })
    return normalized


def _validate_dice(value: Any):
    if not isinstance(value, list) or not value:
        raise DDBRegistryError("tables.dice_values must be a non-empty array")
    normalized = []
    previous = None
    for index, die in enumerate(value):
        if type(die) is not int or die <= 0:
            raise DDBRegistryError(
                f"tables.dice_values[{index}] must be a positive integer")
        if previous is not None and die <= previous:
            reason = "duplicate" if die == previous else "unsorted"
            raise DDBRegistryError(
                f"tables.dice_values contains {reason} value {die}")
        normalized.append(die)
        previous = die
    return normalized


def _semantic_fingerprint(tables) -> str:
    encoded = json.dumps(
        tables,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _deep_freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item)
                                 for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _build_registry(payload: Any) -> DDBRegistry:
    _exact_keys(payload, _ROOT_KEYS, "registry")
    if payload["schema_version"] != REGISTRY_SCHEMA_VERSION:
        raise DDBRegistryError(
            f"unsupported registry schema: {payload['schema_version']!r}")
    _validate_metadata(payload["metadata"])
    _exact_keys(payload["tables"], _TABLE_KEYS, "tables")

    normalized_tables = {
        table: _validate_named_table(payload["tables"][table], table)
        for table in _LOOKUP_TABLES
    }
    normalized_tables["dice_values"] = _validate_dice(
        payload["tables"]["dice_values"])
    fingerprint = _semantic_fingerprint(normalized_tables)
    expected = payload["metadata"]["semantic_fingerprint_sha256"]
    if fingerprint != expected:
        raise DDBRegistryError(
            "semantic registry fingerprint mismatch: "
            f"expected {expected}, computed {fingerprint}")

    immutable_tables = {
        table: MappingProxyType({entry["id"]: entry["name"]
                                 for entry in normalized_tables[table]})
        for table in _LOOKUP_TABLES
    }
    immutable_tables["dice_values"] = tuple(
        normalized_tables["dice_values"])
    return DDBRegistry(
        schema_version=payload["schema_version"],
        metadata=_deep_freeze(payload["metadata"]),
        tables=MappingProxyType(immutable_tables),
        fingerprint=fingerprint,
    )


RegistryPath = Union[str, os.PathLike]


def load_registry(path: Optional[RegistryPath] = None) -> DDBRegistry:
    """Load and strictly validate a registry file.

    With no path, the package's pinned offline artifact is used.  This function
    never performs network access.
    """

    try:
        if path is None:
            target = resources.files("charactercheck").joinpath(
                REGISTRY_RESOURCE)
            with target.open("r", encoding="utf-8") as stream:
                payload = json.load(
                    stream, object_pairs_hook=_duplicate_safe_object)
        else:
            with open(path, "r", encoding="utf-8") as stream:
                payload = json.load(
                    stream, object_pairs_hook=_duplicate_safe_object)
    except DDBRegistryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DDBRegistryError(f"could not load DDB registry: {error}") from error
    return _build_registry(payload)


DDB_REGISTRY = load_registry()
ARMOR_TYPES = DDB_REGISTRY.armor_types
RANGE_TYPES = DDB_REGISTRY.range_types
DAMAGE_TYPES = DDB_REGISTRY.damage_types
WEAPON_PROPERTIES = DDB_REGISTRY.weapon_properties
DICE_VALUES = DDB_REGISTRY.dice_values
REGISTRY_FINGERPRINT = DDB_REGISTRY.fingerprint


__all__ = [
    "ARMOR_TYPES",
    "DAMAGE_TYPES",
    "DDB_REGISTRY",
    "DDBRegistry",
    "DDBRegistryError",
    "DICE_VALUES",
    "RANGE_TYPES",
    "REGISTRY_FINGERPRINT",
    "REGISTRY_RESOURCE",
    "REGISTRY_SCHEMA_VERSION",
    "WEAPON_PROPERTIES",
    "load_registry",
]
