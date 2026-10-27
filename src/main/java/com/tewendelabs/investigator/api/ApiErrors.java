package com.tewendelabs.investigator.api;

import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

@RestControllerAdvice
public class ApiErrors {
    @ExceptionHandler(ApiFailure.class)
    ResponseEntity<ProblemDetail> known(ApiFailure e) {
        return problem(e.status, e.code);
    }

    @ExceptionHandler(DataIntegrityViolationException.class)
    ResponseEntity<ProblemDetail> conflict() {
        return problem(409, "STATE_CONFLICT");
    }

    @ExceptionHandler(MaxUploadSizeExceededException.class)
    ResponseEntity<ProblemDetail> large() {
        return problem(413, "UPLOAD_TOO_LARGE");
    }

    @ExceptionHandler({IllegalArgumentException.class, org.springframework.web.method.annotation.MethodArgumentTypeMismatchException.class,
            org.springframework.http.converter.HttpMessageNotReadableException.class, org.springframework.web.bind.MissingRequestHeaderException.class,
            org.springframework.web.bind.MissingServletRequestParameterException.class, org.springframework.web.multipart.support.MissingServletRequestPartException.class})
    ResponseEntity<ProblemDetail> invalid() {
        return problem(400, "INVALID_REQUEST");
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<ProblemDetail> unexpected() {
        return problem(500, "INTERNAL_ERROR");
    }

    private ResponseEntity<ProblemDetail> problem(int status, String code) {
        ProblemDetail p = ProblemDetail.forStatus(status);
        p.setTitle(code);
        p.setProperty("code", code);
        return ResponseEntity.status(status).body(p);
    }
}
