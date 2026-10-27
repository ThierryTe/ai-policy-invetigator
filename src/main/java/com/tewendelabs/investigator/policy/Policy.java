package com.tewendelabs.investigator.policy;

import java.util.UUID;

import jakarta.persistence.*;

@Entity
@Table(name = "policies")
public class Policy {
    @Id
    private UUID id;
    @Column(name = "organization_id", nullable = false)
    private UUID organizationId;
    @Column(name = "department_id", nullable = false)
    private UUID departmentId;
    @Column(nullable = false, length = 200)
    private String title;
    @Column(nullable = false)
    private String kind;
    @Column(name = "external_processing_allowed", nullable = false)
    private boolean externalProcessingAllowed;

    protected Policy() {
    }

    public UUID getId() {
        return id;
    }

    public UUID getOrganizationId() {
        return organizationId;
    }

    public UUID getDepartmentId() {
        return departmentId;
    }

    public String getTitle() {
        return title;
    }

    public String getKind() {
        return kind;
    }

    public boolean isExternalProcessingAllowed() {
        return externalProcessingAllowed;
    }
}
