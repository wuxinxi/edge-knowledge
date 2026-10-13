"""Bounded YAML scalars and lists. Tags/aliases never create executable objects."""

import math
import re
from datetime import date, datetime

import yaml


class UniqueMappingLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        if len(set(keys)) != len(keys):
            raise yaml.YAMLError("Duplicate metadata keys")
        return super().construct_mapping(node, deep=deep)


class YAMLMetadataReader:
    def read(self, text: str) -> dict:
        lines = text.lstrip("\ufeff").splitlines()
        if not lines or lines[0].strip() != "---":
            return {}
        end = next(
            (i for i, line in enumerate(lines[1:], 1) if line.strip() in {"---", "..."}), None
        )
        if end is None:
            return {}
        block = "\n".join(lines[1:end])
        if len(block) > 65536:
            return {}
        try:
            for i, token in enumerate(yaml.scan(block)):
                if i > 4000 or isinstance(
                    token, (yaml.AliasToken, yaml.AnchorToken, yaml.TagToken)
                ):
                    return {}
            raw = yaml.load(block, Loader=UniqueMappingLoader)
        except (yaml.YAMLError, RecursionError, TypeError, ValueError, OverflowError):
            return {}
        if not isinstance(raw, dict) or len(raw) > 100:
            return {}
        # Preserve only bounded flat, queryable values; originals retain everything else.
        result = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not re.fullmatch(r"[\w\-]{1,64}", key):
                continue
            if isinstance(value, str) and len(value) <= 4000:
                result[key] = value
            elif isinstance(value, (date, datetime)):
                result[key] = value.isoformat()
            elif isinstance(value, (int, float, bool)) and math.isfinite(value):
                result[key] = value
            elif (
                isinstance(value, list)
                and len(value) <= 100
                and all(isinstance(v, str) and len(v) <= 100 for v in value)
            ):
                result[key] = value
        return result
