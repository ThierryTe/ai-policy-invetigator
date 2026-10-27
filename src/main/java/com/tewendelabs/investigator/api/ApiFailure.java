package com.tewendelabs.investigator.api;

public class ApiFailure extends RuntimeException {
    public final int status;
    public final String code;

    public ApiFailure(int status, String code) {
        super(code);
        this.status = status;
        this.code = code;
    }

    public static ApiFailure missing() {
        return new ApiFailure(404, "NOT_FOUND");
    }
}
