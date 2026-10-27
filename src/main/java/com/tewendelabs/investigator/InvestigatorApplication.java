package com.tewendelabs.investigator;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@EnableScheduling
@SpringBootApplication
public class InvestigatorApplication {
    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("--verify-configuration")) {
            System.exit(com.tewendelabs.investigator.config.ConfigurationCheck.run(false));
        }
        if (args.length == 1 && args[0].equals("--verify-meta-access")) {
            System.exit(com.tewendelabs.investigator.config.ConfigurationCheck.run(true));
        }
        if (args.length == 3 && args[0].equals("--extract-pdf")) {
            com.tewendelabs.investigator.ingestion.PdfSandbox.main(new String[]{args[1], args[2]});
            return;
        }
        if (args.length == 3 && args[0].equals("--verify-embeddings")) {
            com.tewendelabs.investigator.ingestion.LocalModelCheck.run(args[1], args[2]); return;
        }
        SpringApplication.run(InvestigatorApplication.class, args);
    }
}
