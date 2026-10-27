package com.tewendelabs.investigator.provider;

import java.time.Duration;

public interface MetaTransport {
    record Reply(int status, String body) {
    }

    Reply send(String key, String payload, Duration timeout);
}
