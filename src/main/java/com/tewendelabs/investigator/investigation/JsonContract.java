package com.tewendelabs.investigator.investigation;

import java.util.*;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import com.tewendelabs.investigator.api.ApiFailure;

/**
 * Validates the restricted JSON Schema vocabulary used by our server-owned contracts.
 */
public final class JsonContract {
    public static final JsonMapper JSON = JsonMapper.builder().build();

    public static JsonNode parse(String raw) {
        try {
            if (raw == null || raw.length() > 100000) throw new IllegalArgumentException();
            return JSON.readTree(raw);
        } catch (RuntimeException e) {
            throw new ApiFailure(502, "MALFORMED_MODEL_OUTPUT");
        }
    }

    public static String encode(Object value) {
        return JSON.writeValueAsString(value);
    }

    public static JsonNode tree(Object value) {
        return JSON.valueToTree(value);
    }

    public static void validate(JsonNode value, JsonNode schema) {
        boolean valid = false;
        JsonNode types = schema.get("type");
        for (JsonNode type : types.isArray() ? types : tree(List.of(types.asString()))) {
            valid |= switch (type.asString()) {
                case "object" -> value.isObject();
                case "array" -> value.isArray();
                case "string" -> value.isString();
                case "boolean" -> value.isBoolean();
                case "null" -> value.isNull();
                default -> false;
            };
        }
        if (!valid) fail();
        if (schema.has("enum")) {
            boolean match = false;
            for (var option : schema.get("enum")) match |= option.equals(value);
            if (!match) fail();
        }
        if (value.isObject()) {
            JsonNode properties = schema.get("properties");
            for (String name : value.propertyNames()) if (!properties.has(name)) fail();
            for (var name : schema.get("required")) if (!value.has(name.asString())) fail();
            for (String name : value.propertyNames()) validate(value.get(name), properties.get(name));
        }
        if (value.isArray()) {
            if (value.size() > schema.path("maxItems").asInt(100) || value.size() < schema.path("minItems").asInt(0))
                fail();
            for (var item : value) validate(item, schema.get("items"));
        }
        if (value.isString() && (value.asString().length() > schema.path("maxLength").asInt(12000) || value.asString().length() < schema.path("minLength").asInt(0)))
            fail();
    }

    public static void fail() {
        throw new ApiFailure(502, "INVALID_MODEL_SCHEMA");
    }

    public static Map<String, Object> object(Map<String, Object> properties) {
        return Map.of("type", "object", "properties", properties, "required", new ArrayList<>(properties.keySet()), "additionalProperties", false);
    }

    public static Map<String, Object> text() {
        return Map.of("type", "string", "maxLength", 2000);
    }

    public static Map<String, Object> nullable() {
        return Map.of("type", List.of("string", "null"), "maxLength", 2000);
    }

    public static Map<String, Object> strings() {
        return array(text(), 0, 30);
    }

    public static Map<String, Object> array(Object items, int min, int max) {
        return Map.of("type", "array", "items", items, "minItems", min, "maxItems", max);
    }

    public static Map<String, Object> choice(String... values) {
        return Map.of("type", "string", "enum", List.of(values));
    }
}
