from src.data_platform.persistence.models import SqlStatement

SEMANTIC_LAYER_STATEMENTS: list[SqlStatement] = [
    SqlStatement(sql="""
        CREATE TABLE IF NOT EXISTS business_domain (
            domain_code VARCHAR(64) PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            description TEXT,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """),
    SqlStatement(sql="""
        CREATE TABLE IF NOT EXISTS value_domain (
            domain_code VARCHAR(128) PRIMARY KEY,
            name VARCHAR(256) NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """),
    SqlStatement(sql="""
        CREATE TABLE IF NOT EXISTS value_domain_mapping (
            id SERIAL PRIMARY KEY,
            domain_code VARCHAR(128) NOT NULL REFERENCES value_domain(domain_code),
            source_value VARCHAR(512) NOT NULL,
            standard_value VARCHAR(512) NOT NULL,
            description TEXT,
            UNIQUE(domain_code, source_value)
        )
    """),
    SqlStatement(sql="""
        CREATE TABLE IF NOT EXISTS business_object (
            object_code VARCHAR(64) PRIMARY KEY,
            domain_code VARCHAR(64) NOT NULL REFERENCES business_domain(domain_code),
            name VARCHAR(128) NOT NULL,
            definition TEXT,
            identifier VARCHAR(128),
            source_object VARCHAR(256),
            source_adapter_port VARCHAR(256),
            relations JSONB DEFAULT '[]'::jsonb,
            version VARCHAR(32) DEFAULT '1.0',
            status VARCHAR(32) DEFAULT 'draft',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """),
    SqlStatement(sql="""
        CREATE TABLE IF NOT EXISTS metric (
            metric_code VARCHAR(256) PRIMARY KEY,
            object_code VARCHAR(64) NOT NULL REFERENCES business_object(object_code),
            name VARCHAR(256) NOT NULL,
            definition TEXT,
            metric_type VARCHAR(32) DEFAULT 'Atomic',
            semantic_type VARCHAR(32),
            unit VARCHAR(64),
            required BOOLEAN DEFAULT FALSE,
            default_value JSONB,
            source_object VARCHAR(256),
            source_field VARCHAR(256),
            source_adapter_port VARCHAR(256),
            transformation JSONB,
            value_domain VARCHAR(128) REFERENCES value_domain(domain_code),
            importance VARCHAR(32) DEFAULT 'optional',
            usage_count INTEGER DEFAULT 0,
            quality_score FLOAT DEFAULT 0.0,
            version VARCHAR(32) DEFAULT '1.0',
            status VARCHAR(32) DEFAULT 'draft',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """),
    SqlStatement(sql="""
        CREATE TABLE IF NOT EXISTS metric_source_binding (
            binding_id VARCHAR(64) PRIMARY KEY,
            metric_code VARCHAR(256) NOT NULL REFERENCES metric(metric_code),
            source_type VARCHAR(32) NOT NULL,
            source_ref VARCHAR(512) NOT NULL,
            source_field VARCHAR(256) NOT NULL,
            source_version VARCHAR(128) NOT NULL,
            evidence TEXT NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'draft',
            reviewed_by VARCHAR(128),
            reviewed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(metric_code, source_type, source_ref, source_field, source_version)
        )
    """),
    SqlStatement(sql="""
        CREATE TABLE IF NOT EXISTS source_value_mapping (
            mapping_id VARCHAR(64) PRIMARY KEY,
            metric_code VARCHAR(256) NOT NULL REFERENCES metric(metric_code),
            domain_code VARCHAR(128) NOT NULL REFERENCES value_domain(domain_code),
            binding_id VARCHAR(64) NOT NULL REFERENCES metric_source_binding(binding_id),
            source_value VARCHAR(512) NOT NULL,
            standard_value VARCHAR(512) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'draft',
            reviewed_by VARCHAR(128),
            reviewed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(binding_id, source_value)
        )
    """),
    SqlStatement(sql="""
        CREATE TABLE IF NOT EXISTS standard_value_proposal (
            proposal_id VARCHAR(64) PRIMARY KEY,
            domain_code VARCHAR(128) NOT NULL REFERENCES value_domain(domain_code),
            standard_value VARCHAR(512) NOT NULL,
            evidence TEXT NOT NULL,
            source_ref VARCHAR(512) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'draft',
            reviewed_by VARCHAR(128),
            reviewed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(domain_code, standard_value, source_ref)
        )
    """),
]
