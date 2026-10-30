package com.tewendelabs.investigator.security;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class DatabaseSafetyCheck implements ApplicationRunner {
    private final JdbcTemplate jdbc;
    private volatile boolean ready;

    public boolean ready() {
        return ready;
    }

    @org.springframework.context.event.EventListener(org.springframework.boot.context.event.ApplicationReadyEvent.class)
    public void applicationReady() {
        ready = true;
    }

    public DatabaseSafetyCheck(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public void run(ApplicationArguments args) {
        Boolean unsafe = jdbc.queryForObject("""
                select exists(select 1 from pg_roles where rolname=current_user and (rolsuper or rolbypassrls))
                 or exists(select 1 from pg_class c join pg_roles r on r.oid=c.relowner
                           where c.relnamespace='public'::regnamespace and c.relname in ('policies','policy_versions','document_pages','chunks','investigations','requirement_extractions','investigation_assessments','finding_reviews')
                            and (r.rolname=current_user or pg_has_role(current_user,r.oid,'MEMBER') or r.rolsuper or r.rolbypassrls))
                 or exists(select 1 from pg_class c join pg_roles r on r.oid=c.relowner
                           where c.relnamespace='public'::regnamespace and c.relname in ('demo_access','demo_meta_budget')
                            and (r.rolname=current_user or pg_has_role(current_user,r.oid,'MEMBER') or r.rolsuper or r.rolbypassrls))
                 or has_table_privilege(current_user,'demo_access','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
                 or has_table_privilege(current_user,'demo_meta_budget','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
                 or has_function_privilege(current_user,'reserve_demo_work(text,bigint)','EXECUTE')
                 or exists(select 1 from pg_proc f join pg_roles r on r.oid=f.proowner
                           where f.pronamespace='public'::regnamespace and f.prosecdef
                           and f.proname in ('can_access_policy','active_identity','login_identity','actor_memberships',
                             'reserve_demo_work','enqueue_ingestion','visible_job','previous_submission','claim_ingestion','finish_ingestion','heartbeat_ingestion','version_job','schedule_investigation','claim_investigation','reserve_investigation_call','record_investigation_usage','finish_investigation','investigation_progress','checkpoint_investigation')
                           and (r.rolsuper or r.rolbypassrls))
                """, Boolean.class);
        Boolean enforced = jdbc.queryForObject("""
                select count(*)=8 and bool_and(relrowsecurity and relforcerowsecurity)
                from pg_class where relnamespace='public'::regnamespace
                  and relname in ('policies','policy_versions','document_pages','chunks','investigations','requirement_extractions','investigation_assessments','finding_reviews')
                """, Boolean.class);
        if (!Boolean.TRUE.equals(enforced) || !Boolean.FALSE.equals(unsafe))
            throw new IllegalStateException("Database roles do not satisfy the RLS security boundary");
    }
}
