package qualification;

import java.nio.file.*;
import java.security.MessageDigest;
import java.nio.*;
import java.util.*;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tewendelabs.investigator.InvestigatorApplication;
import com.tewendelabs.investigator.ingestion.*;
import com.tewendelabs.investigator.security.DatabaseSafetyCheck;
import com.tewendelabs.investigator.provider.*;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.ai.transformers.TransformersEmbeddingModel;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.DefaultApplicationArguments;
import org.springframework.boot.autoconfigure.condition.ConditionEvaluationReport;
import org.springframework.boot.web.server.context.WebServerApplicationContext;

/** Qualification only: loaded beside, never replacing, the immutable production JAR. */
public final class ProductionProbe {
    static final String EXPECTED_JAR = System.getProperty("qualification.jar-sha256", "");
    static final String MODEL = "file:/models/model.onnx", TOKENIZER = "file:/models/tokenizer.json";
    static final String REVISION = "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452:be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037";
    static final Map<String,Object> result = new LinkedHashMap<>();
    static final List<Map<String,Object>> checks = new ArrayList<>();
    static String stage = "identity";
    static String sha(byte[] b) throws Exception { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b)); }
    static String fileSha(Path p) throws Exception {
        var md = MessageDigest.getInstance("SHA-256");
        try (var in = Files.newInputStream(p)) { byte[] b = new byte[65536]; int n; while ((n=in.read(b))!=-1) md.update(b,0,n); }
        return HexFormat.of().formatHex(md.digest());
    }
    static void require(boolean ok,String name,Object observed) {
        checks.add(Map.of("name",name,"status",ok?"PASS":"FAIL","observed",observed));
        if (!ok) throw new IllegalStateException(name);
    }
    static double cosine(float[] a,float[] b) { double ab=0,aa=0,bb=0; for(int i=0;i<a.length;i++){ab+=(double)a[i]*b[i];aa+=(double)a[i]*a[i];bb+=(double)b[i]*b[i];} return ab/Math.sqrt(aa*bb); }
    static List<Map<String,Object>> vectors(List<float[]> rows) throws Exception {
        List<Map<String,Object>> out = new ArrayList<>();
        for(float[] row:rows) {
            EmbeddingGateway.vectorLiteral(row);
            double norm=0; ByteBuffer buf=ByteBuffer.allocate(4*row.length).order(ByteOrder.LITTLE_ENDIAN);
            for(float f:row){norm+=(double)f*f;buf.putFloat(f);}
            out.add(Map.of("dimensions",row.length,"l2Norm",Math.sqrt(norm),"float32LittleEndianSha256",sha(buf.array()),"finiteNonzero",true));
        }
        return out;
    }
    static void inference(EmbeddingGateway gateway) throws Exception {
        stage="inference";
        String sentence="Report security incidents within 24 hours.";
        var single=gateway.embed(List.of(sentence));
        require(single.size()==1,"single_inference",vectors(single));
        var batch=gateway.embed(List.of(sentence,"Security incidents must be reported within one day.","Travel meals are reimbursed.","Synthetic policy: café employees must report an incident.\nRésumé — 24 hours."));
        require(batch.size()==4,"mixed_length_unicode_batch",vectors(batch));
        double consistent=cosine(single.getFirst(),batch.getFirst());
        require(consistent>0.999,"single_batch_consistency",consistent);
        var repeat=gateway.embed(List.of(sentence));
        require(cosine(single.getFirst(),repeat.getFirst())>0.999999,"repeat_inference",vectors(repeat));
        double related=cosine(batch.get(0),batch.get(1)),unrelated=cosine(batch.get(0),batch.get(2));
        require(related>unrelated,"representative_semantic_ranking",Map.of("relatedCosine",related,"unrelatedCosine",unrelated));
        var maxBatch=gateway.embed(Collections.nCopies(32,sentence));
        require(maxBatch.size()==32,"maximum_supported_batch_32",vectors(maxBatch));
        boolean rejected=false;
        try { gateway.embed(Collections.nCopies(33,sentence)); } catch(IllegalArgumentException expected){rejected=true;}
        require(rejected,"batch_33_rejected",rejected);
        var cleaned=gateway.embed(List.of("  Report\u0001  security incidents within 24 hours.\r\n"));
        require(cosine(single.getFirst(),cleaned.getFirst())>0.999999,"packaged_text_cleaning",vectors(cleaned));
    }
    static Object field(Object o,String name) throws Exception { var f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o); }
    static void context() throws Exception {
        stage="spring_application_context_startup";
        try(var ctx=SpringApplication.run(InvestigatorApplication.class)) {
            require(ctx.isActive(),"whole_application_context_active",ctx.getClass().getName());
            var e=ctx.getEnvironment();
            Map<String,String> effective=new TreeMap<>();
            for(String p:List.of("app.environment","spring.ai.model.embedding","spring.ai.embedding.transformer.onnx.model-uri","spring.ai.embedding.transformer.tokenizer.uri","spring.ai.embedding.transformer.tokenizer.options.padding","app.embedding.revision","app.worker.enabled","app.investigation.worker-enabled","spring.flyway.enabled","spring.jpa.hibernate.ddl-auto","spring.datasource.url","spring.datasource.username","springdotenv.enabled")) effective.put(p,e.getProperty(p,"<unset>"));
            result.put("effectiveConfiguration",effective);
            require("production".equals(e.getProperty("app.environment")) && "transformers".equals(e.getProperty("spring.ai.model.embedding")),"production_neural_configuration",effective);
            require(ctx.getBeansOfType(EmbeddingModel.class).size()==1,"single_real_embedding_model",ctx.getBeansOfType(EmbeddingModel.class).keySet());
            var model=ctx.getBean(EmbeddingModel.class);
            require(model instanceof TransformersEmbeddingModel,"transformer_auto_configuration",model.getClass().getName());
            var conditions=ConditionEvaluationReport.get(ctx.getBeanFactory()).getConditionAndOutcomesBySource();
            result.put("transformerConditions",conditions.entrySet().stream().filter(v->v.getKey().contains("Transformers")).map(v->Map.of("source",v.getKey(),"fullMatch",v.getValue().isFullMatch())).toList());
            require(ctx.getBean(DatabaseSafetyCheck.class).ready(),"real_database_safety_runner_completed",true);
            require(ctx.getBeansOfType(EmbeddingArtifactCheck.class).size()==1,"real_embedding_artifact_runner_present",true);
            require(!(boolean)field(ctx.getBean(IngestionWorker.class),"enabled") && !(boolean)field(ctx.getBean(com.tewendelabs.investigator.investigation.InvestigationWorker.class),"enabled"),"both_workers_disabled",true);
            boolean metaDisabled=false;
            try {ctx.getBean(PolicyReasoningProvider.class).reason(null);} catch(com.tewendelabs.investigator.api.ApiFailure failure){metaDisabled="META_KEY_MISSING".equals(failure.code);}
            require(metaDisabled,"external_meta_calls_fail_closed_without_key",true);
            require(ctx.getBeansOfType(org.flywaydb.core.Flyway.class).isEmpty(),"flyway_absent_disabled",true);
            stage="http_health";
            int port=((WebServerApplicationContext)ctx).getWebServer().getPort();
            var client=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
            var reply=client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/actuator/health")).timeout(Duration.ofSeconds(10)).GET().build(),HttpResponse.BodyHandlers.ofString());
            require(reply.statusCode()==200 && reply.body().contains("UP"),"http_health_up",Map.of("status",reply.statusCode(),"body",reply.body()));
            for(String route:List.of("/v3/api-docs","/swagger-ui/index.html","/api/policies")) {
                var r=client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+route)).timeout(Duration.ofSeconds(10)).GET().build(),HttpResponse.BodyHandlers.ofString());
                require(r.statusCode()==401 || r.statusCode()==403,"production_http_denied_"+route,r.statusCode());
            }
            result.put("startupStatus","PASS");
            result.put("rawInferenceDiagnostics",rawDiagnostics(model));
            require(((List<?>)result.get("rawInferenceDiagnostics")).stream()
                    .allMatch(v->"PASS".equals(((Map<?,?>)v).get("status"))),"raw_model_inference",true);
            inference(ctx.getBean(EmbeddingGateway.class));
        }
        require(true,"application_context_closed",true);
    }
    static List<Map<String,Object>> rawDiagnostics(EmbeddingModel model) {
        List<Map<String,Object>> out=new ArrayList<>();
        for(List<String> input:List.of(List.of("Report security incidents within 24 hours."),List.of("Report security incidents within 24 hours.","Travel meals are reimbursed."))) {
            Map<String,Object> item=new LinkedHashMap<>();item.put("syntheticInputs",input);
            try { item.put("vectors",vectors(model.embed(input)));item.put("status","PASS"); }
            catch(Throwable failure) {
                item.put("status","FAIL");List<Map<String,String>> causes=new ArrayList<>();
                for(Throwable t=failure;t!=null;t=t.getCause()) causes.add(Map.of("class",t.getClass().getName(),"message",String.valueOf(t.getMessage())));
                item.put("causes",causes);failure.printStackTrace();
            }
            out.add(item);
        }
        return out;
    }
    public static void main(String[] args) throws Exception {
        String mode=args[0]; int exit=0;
        result.put("mode",mode);result.put("checks",checks);
        result.put("runtime",Map.of("javaVersion",System.getProperty("java.runtime.version"),"javaVendor",System.getProperty("java.vendor"),"os",System.getProperty("os.name"),"architecture",System.getProperty("os.arch"),"maxHeapBytes",Runtime.getRuntime().maxMemory(),"userHome",System.getProperty("user.home")));
        try {
            require(EXPECTED_JAR.matches("[0-9a-f]{64}") && EXPECTED_JAR.equals(fileSha(Path.of("/app/investigator.jar"))),"exact_production_jar_identity",fileSha(Path.of("/app/investigator.jar")));
            try(var fresh=Files.list(Path.of("/runtime"))) { require(fresh.findAny().isEmpty(),"fresh_runtime_scratch",true); }
            require("/tmp/embedding-native".equals(System.getenv("DJL_CACHE_DIR")),"image_uses_ephemeral_native_scratch",String.valueOf(System.getenv("DJL_CACHE_DIR")));
            require(!Files.exists(Path.of("/tmp/embedding-native")),"fresh_native_scratch",true);
            require(ai.djl.util.Utils.isOfflineMode(),"image_enforces_djl_offline",ai.djl.util.Utils.isOfflineMode());
            require("Rust".equals(ai.djl.engine.Engine.getDefaultEngineName()),"image_selects_rust_engine",ai.djl.engine.Engine.getDefaultEngineName());
            require("Rust".equals(ai.djl.engine.Engine.getInstance().getEngineName()),"actual_rust_engine",ai.djl.engine.Engine.getInstance().getEngineName());
            require("true".equals(System.getenv("OPT_OUT_TRACKING")),"image_disables_djl_telemetry",String.valueOf(System.getenv("OPT_OUT_TRACKING")));
            result.put("codeSources",Map.of("application",InvestigatorApplication.class.getProtectionDomain().getCodeSource().getLocation().toString(),"transformer",TransformersEmbeddingModel.class.getProtectionDomain().getCodeSource().getLocation().toString(),"onnx",ai.onnxruntime.OrtEnvironment.class.getProtectionDomain().getCodeSource().getLocation().toString(),"tokenizer",ai.djl.huggingface.tokenizers.HuggingFaceTokenizer.class.getProtectionDomain().getCodeSource().getLocation().toString()));
            stage="model_artifact_hashes";
            new EmbeddingArtifactCheck(MODEL,TOKENIZER,REVISION).run(new DefaultApplicationArguments());
            require(true,"packaged_model_hash_verification",REVISION);
            if(mode.equals("manual")) {
                stage="real_model_initialization";
                try(var model=new TransformersEmbeddingModel()) {
                    model.setModelResource(MODEL);model.setTokenizerResource(TOKENIZER);model.setTokenizerOptions(Map.of("padding","true"));
                    model.afterPropertiesSet();
                    require(true,"real_model_initialization",model.getClass().getName());
                    inference(new EmbeddingGateway(model,new TextCleaningService(),REVISION));
                }
            } else if(mode.equals("context")) context();
            else throw new IllegalArgumentException("unknown mode");
            result.put("status","PASS");
        } catch(Throwable failure) {
            result.put("status","FAIL");result.put("failedStage",stage);
            List<Map<String,String>> causes=new ArrayList<>();
            for(Throwable t=failure;t!=null;t=t.getCause()) causes.add(Map.of("class",t.getClass().getName(),"message",String.valueOf(t.getMessage())));
            result.put("causes",causes); failure.printStackTrace();exit=1;
        } finally {
            try(var lines=Files.lines(Path.of("/proc/self/maps"))) {result.put("loadedNativeMappings",lines.filter(v->v.contains("onnx")||v.contains("tokenizers")).toList());}
            Map<String,String> natives=new TreeMap<>();
            for(String dir:List.of("/tmp","/runtime")) try(var files=Files.walk(Path.of(dir))) {for(Path p:files.filter(Files::isRegularFile).filter(v->v.toString().endsWith(".so")).toList()) natives.put(p.toString(),fileSha(p));}
            result.put("nativeLibrarySha256",natives);
            Files.writeString(Path.of("/results/"+mode+".json"),new ObjectMapper().writerWithDefaultPrettyPrinter().writeValueAsString(result)+"\n");
        }
        System.exit(exit);
    }
}
