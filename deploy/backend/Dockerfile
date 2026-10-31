# Build the existing Java application without host Maven/JDK or host-built artifacts.
FROM eclipse-temurin:21-jdk-jammy@sha256:4e61d0b3471137e239397789661f6adeaf8db9adcfae45916b22f628c8a32dc0 AS build
WORKDIR /workspace
COPY pom.xml ./
COPY --chmod=0755 mvnw ./mvnw
COPY .mvn/wrapper/maven-wrapper.properties ./.mvn/wrapper/maven-wrapper.properties
COPY src ./src
RUN --mount=type=cache,target=/root/.m2 ./mvnw -B -Pneural-embeddings -Dmaven.test.skip=true package

# Retain the exact Java runtime image used by the verified local workflow.
FROM eclipse-temurin:21-jre-jammy@sha256:affcab5356e1270ac35d2361ee83135af2f03e8d580eca78a6d5d6fdbf048db0
WORKDIR /app
# Rust comes from pinned tokenizers-0.36.0; never acquire a native engine online.
ENV DJL_DEFAULT_ENGINE=Rust DJL_OFFLINE=true OPT_OUT_TRACKING=true DJL_CACHE_DIR=/tmp/embedding-native
COPY --from=build --chown=10001:10001 /workspace/target/ai-policy-investigator-0.1.0-SNAPSHOT.jar /app/investigator.jar
USER 10001:10001
CMD ["java", "-Xmx512m", "-Duser.home=/runtime", "-jar", "/app/investigator.jar"]
