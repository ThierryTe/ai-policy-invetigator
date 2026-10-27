# Attribution and licensing inventory

Selected source files originate in ThierryTe/spring-ai-rag at the commit recorded in
docs/provenance/allowlist.json. Reuse is based on the project owner's explicit
permission. No top-level license was present in the inspected source snapshot; no
license grant beyond that permission is invented here. Preserve source notices in
any additional imports.

The imported Maven wrapper scripts retain their original Apache license headers.
Runtime/test libraries retain their respective upstream licenses; dependency
resolution and a distributable license inventory must be reviewed before release.
No model weights are distributed. The selected model repository, pinned revision,
Apache-2.0 model-card license and verified artifact hashes are recorded in
`docs/provenance/embedding-model.json`. Runtime DJL/PyTorch native dependencies are
downloaded into an ignored local cache; they are not copied from the reference project.

The frontend repository has been inspected only; no frontend assets or code were
copied in this phase.


The local OpenAPI follow-up resolves `org.projectlombok:lombok:1.18.46` under the
MIT license (compile-time tool, excluded from the executable runtime JAR),
`org.springdoc:springdoc-openapi-starter-webmvc-ui:3.2.0` under Apache-2.0, and its
transitive `org.webjars:swagger-ui:5.34.0` under Apache-2.0. Versions/licenses were
checked against resolved Maven POM metadata. These are dependency additions, not
source imports from the reference repositories. Upstream notices remain applicable.
