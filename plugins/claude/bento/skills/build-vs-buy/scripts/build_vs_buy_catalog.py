from __future__ import annotations


FRAMEWORK_ALIASES = {
    "react": ("react",),
    "nextjs": ("next",),
    "vite": ("vite",),
    "vue": ("vue",),
    "nuxt": ("nuxt",),
    "sveltekit": ("@sveltejs/kit", "sveltekit"),
    "express": ("express",),
    "fastify": ("fastify",),
    "nestjs": ("@nestjs/core",),
    "django": ("django",),
    "flask": ("flask",),
    "fastapi": ("fastapi",),
    "rails": ("rails",),
    "laravel": ("laravel/framework",),
    "spring-boot": ("org.springframework.boot:*", "spring-boot-starter*"),
    "aspnet-core": ("microsoft.aspnetcore.*",),
}


TOOL_CATEGORIES = {
    "cloud_providers": {
        "aws": (
            "@aws-sdk/*",
            "aws-sdk",
            "aws-sdk-*",
            "boto3",
            "botocore",
            "github.com/aws/aws-sdk-go-v2/*",
        ),
        "gcp": (
            "@google-cloud/*",
            "google-cloud-*",
            "cloud.google.com/go/*",
            "google.golang.org/api",
        ),
        "azure": ("@azure/*", "azure-*", "github.com/azure/*"),
        "cloudflare": ("cloudflare", "wrangler"),
        "digitalocean": ("godo", "digitalocean"),
    },
    "relational_databases": {
        "postgres": ("pg", "postgres", "postgresql", "psycopg", "psycopg2", "lib/pq", "jackc/pgx*", "gorm.io/driver/postgres"),
        "mysql": ("mysql", "mysql2", "pymysql", "gorm.io/driver/mysql"),
        "mariadb": ("mariadb",),
        "sqlite": ("sqlite", "sqlite3", "better-sqlite3", "gorm.io/driver/sqlite"),
        "sqlserver": ("mssql", "sqlserver", "gorm.io/driver/sqlserver"),
    },
    "document_databases": {
        "mongodb": ("mongodb", "mongoose", "motor", "pymongo", "go.mongodb.org/mongo-driver"),
        "couchbase": ("couchbase",),
    },
    "key_value_and_cache": {
        "redis": ("redis", "ioredis", "redis-py", "github.com/redis/*", "github.com/go-redis/*"),
        "memcached": ("memcached", "pylibmc"),
    },
    "managed_nosql": {
        "dynamodb": ("@aws-sdk/client-dynamodb", "boto3", "aws-sdk-client-dynamodb"),
        "firestore": ("firebase-admin", "@google-cloud/firestore", "google-cloud-firestore"),
    },
    "orms_and_query_layers": {
        "prisma": ("prisma", "@prisma/client"),
        "drizzle": ("drizzle-orm", "drizzle-kit"),
        "typeorm": ("typeorm",),
        "sequelize": ("sequelize",),
        "knex": ("knex",),
        "sqlalchemy": ("sqlalchemy",),
        "django-orm": ("django",),
        "activerecord": ("activerecord", "rails"),
        "gorm": ("gorm.io/gorm",),
        "ent": ("entgo.io/ent",),
        "diesel": ("diesel",),
        "ecto": ("ecto",),
    },
    "migration_tools": {
        "prisma-migrate": ("prisma",),
        "drizzle-kit": ("drizzle-kit",),
        "knex-migrations": ("knex",),
        "alembic": ("alembic",),
        "django-migrations": ("django",),
        "goose": ("github.com/pressly/goose*",),
        "flyway": ("flyway-core",),
        "liquibase": ("liquibase-core",),
    },
    "queues": {
        "redis-queue": ("bullmq", "bull", "bee-queue", "rq", "sidekiq", "huey"),
        "rabbitmq": ("amqplib", "pika", "bunny", "github.com/rabbitmq/*"),
        "sqs": ("@aws-sdk/client-sqs", "boto3"),
        "kafka": ("kafkajs", "confluent-kafka", "sarama", "segmentio/kafka-go"),
        "nats": ("nats", "nats.py", "github.com/nats-io/*"),
        "google-pubsub": ("@google-cloud/pubsub", "google-cloud-pubsub"),
    },
    "job_runtimes": {
        "bullmq": ("bullmq",),
        "celery": ("celery",),
        "sidekiq": ("sidekiq",),
        "rq": ("rq",),
        "hangfire": ("hangfire*",),
    },
    "workflow_engines": {
        "temporal": ("@temporalio/*", "temporalio", "go.temporal.io/sdk"),
        "airflow": ("apache-airflow",),
        "argo-workflows": ("argo-workflows",),
    },
    "search_engines": {
        "elasticsearch": ("@elastic/elasticsearch", "elasticsearch", "elasticsearch-dsl"),
        "opensearch": ("@opensearch-project/*", "opensearch-py"),
        "meilisearch": ("meilisearch", "meilisearch-go"),
        "typesense": ("typesense",),
        "algolia": ("algoliasearch",),
    },
    "vector_stores": {
        "pgvector": ("pgvector",),
        "pinecone": ("@pinecone-database/*", "pinecone"),
        "weaviate": ("weaviate-client", "weaviate"),
        "qdrant": ("qdrant-client", "qdrant"),
        "milvus": ("pymilvus", "milvus"),
        "chroma": ("chromadb",),
    },
    "identity_providers": {
        "auth0": ("auth0",),
        "clerk": ("@clerk/*",),
        "cognito": ("amazon-cognito-identity-js",),
        "firebase-auth": ("firebase", "firebase-admin"),
        "supabase-auth": ("@supabase/supabase-js", "supabase"),
        "keycloak": ("keycloak", "keycloak-js"),
        "ory": ("@ory/*", "ory-client"),
    },
    "auth_frameworks": {
        "authjs-nextauth": ("next-auth", "@auth/core"),
        "passport": ("passport",),
        "lucia": ("lucia",),
        "django-auth": ("django",),
        "devise": ("devise",),
    },
    "object_storage": {
        "s3": ("@aws-sdk/client-s3", "boto3", "minio"),
        "gcs": ("@google-cloud/storage", "google-cloud-storage"),
        "azure-blob": ("@azure/storage-blob", "azure-storage-blob"),
        "cloudinary": ("cloudinary",),
        "uploadthing": ("uploadthing",),
        "supabase-storage": ("@supabase/supabase-js", "supabase"),
    },
    "email_providers": {
        "sendgrid": ("@sendgrid/*", "sendgrid"),
        "postmark": ("postmark",),
        "resend": ("resend",),
        "ses": ("@aws-sdk/client-ses", "boto3"),
        "mailgun": ("mailgun.js", "mailgun"),
    },
    "payment_providers": {
        "stripe": ("stripe",),
        "paddle": ("paddle",),
        "chargebee": ("chargebee",),
        "braintree": ("braintree",),
    },
    "analytics_providers": {
        "segment": ("@segment/*", "analytics-node", "segment"),
        "posthog": ("posthog-js", "posthog-node", "posthog"),
        "amplitude": ("@amplitude/*", "amplitude"),
        "mixpanel": ("mixpanel",),
    },
    "feature_flag_providers": {
        "launchdarkly": ("launchdarkly*",),
        "unleash": ("unleash-client", "unleash-proxy-client"),
        "flagsmith": ("flagsmith",),
        "growthbook": ("@growthbook/*", "growthbook"),
    },
    "error_tracking": {
        "sentry": ("@sentry/*", "sentry-sdk", "getsentry/sentry-go"),
        "rollbar": ("rollbar",),
        "bugsnag": ("bugsnag",),
    },
    "metrics_and_monitoring": {
        "datadog": ("datadog", "dd-trace"),
        "prometheus": ("prom-client", "prometheus-client", "prometheus"),
        "grafana": ("grafana",),
        "new-relic": ("newrelic", "new-relic"),
    },
    "tracing_and_otel": {
        "opentelemetry": ("@opentelemetry/*", "opentelemetry-*", "opentelemetry"),
        "honeycomb": ("honeycomb-beeline", "libhoney"),
    },
}


FILE_SIGNAL_PATTERNS = {
    "deployment_targets": {
        "docker": ("dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"),
        "kubernetes": ("k8s/", "kubernetes/", "helm/", "chart.yaml"),
        "helm": ("helm/", "chart.yaml"),
        "serverless": ("serverless.yml", "serverless.yaml", "samconfig.toml", "template.yaml"),
        "vm": ("vagrantfile",),
        "static-site": ("netlify.toml",),
    },
    "hosting_platforms": {
        "vercel": ("vercel.json", ".vercel/"),
        "netlify": ("netlify.toml",),
        "cloudflare": ("wrangler.toml",),
        "flyio": ("fly.toml",),
        "render": ("render.yaml", "render.yml"),
        "railway": ("railway.json", "railway.toml"),
        "heroku": ("procfile", "app.json"),
        "aws-lambda": ("serverless.yml", "serverless.yaml", "samconfig.toml"),
        "cloud-run": ("cloudrun",),
        "ecs": ("ecs",),
        "azure-app-service": ("azure",),
        "digitalocean-app-platform": ("do-app",),
    },
    "cloud_providers": {
        "aws": ("terraform/aws/", "infra/aws/", ".aws/"),
        "gcp": ("terraform/gcp/", "infra/gcp/", "google/"),
        "azure": ("terraform/azure/", "infra/azure/"),
        "cloudflare": ("cloudflare/",),
        "digitalocean": ("digitalocean/",),
    },
}


TEXT_SIGNAL_PATTERNS = {
    "cloud_providers": {
        "aws": ("aws-actions/configure-aws-credentials", "aws_region", "s3://", "arn:aws:", "aws_access_key_id"),
        "gcp": ("google_cloud_project", "gcp_project", "cloud run", "gcr.io", "artifactregistry"),
        "azure": ("azure_tenant_id", "azure_subscription_id", "azure client id"),
        "cloudflare": ("cloudflare_api_token", "wrangler"),
        "digitalocean": ("digitalocean", "doctl"),
    },
    "hosting_platforms": {
        "vercel": ("vercel",),
        "netlify": ("netlify",),
        "cloudflare": ("cloudflare pages", "workers.dev"),
        "flyio": ("fly.io",),
        "render": ("render.com",),
        "railway": ("railway.app",),
        "heroku": ("heroku",),
        "cloud-run": ("cloud run",),
        "ecs": ("amazon ecs",),
        "digitalocean-app-platform": ("app platform",),
    },
    "deployment_targets": {
        "docker": ("docker build", "docker compose"),
        "kubernetes": ("kind: deployment", "helm"),
        "serverless": ("aws::serverless", "serverless"),
    },
}


ENV_SIGNAL_PATTERNS = {
    "cloud_providers": {
        "aws": ("AWS_",),
        "gcp": ("GOOGLE_CLOUD_", "GCP_", "GCLOUD_"),
        "azure": ("AZURE_",),
        "cloudflare": ("CLOUDFLARE_",),
        "digitalocean": ("DIGITALOCEAN_", "DO_"),
    },
    "key_value_and_cache": {"redis": ("REDIS_", "UPSTASH_REDIS_")},
    "search_engines": {
        "meilisearch": ("MEILISEARCH_",),
        "algolia": ("ALGOLIA_",),
        "typesense": ("TYPESENSE_",),
        "elasticsearch": ("ELASTICSEARCH_",),
        "opensearch": ("OPENSEARCH_",),
    },
    "vector_stores": {
        "pinecone": ("PINECONE_",),
        "weaviate": ("WEAVIATE_",),
        "qdrant": ("QDRANT_",),
        "chroma": ("CHROMA_",),
        "pgvector": ("PGVECTOR_",),
    },
    "identity_providers": {
        "auth0": ("AUTH0_",),
        "clerk": ("CLERK_",),
        "cognito": ("COGNITO_",),
        "firebase-auth": ("FIREBASE_",),
        "supabase-auth": ("SUPABASE_",),
        "keycloak": ("KEYCLOAK_",),
    },
    "object_storage": {
        "s3": ("S3_", "AWS_S3_"),
        "gcs": ("GCS_", "GOOGLE_STORAGE_"),
        "azure-blob": ("AZURE_STORAGE_",),
        "cloudinary": ("CLOUDINARY_",),
        "supabase-storage": ("SUPABASE_",),
    },
    "email_providers": {
        "sendgrid": ("SENDGRID_",),
        "postmark": ("POSTMARK_",),
        "resend": ("RESEND_",),
        "ses": ("SES_", "AWS_SES_"),
        "mailgun": ("MAILGUN_",),
    },
    "payment_providers": {
        "stripe": ("STRIPE_",),
        "paddle": ("PADDLE_",),
        "chargebee": ("CHARGEBEE_",),
        "braintree": ("BRAINTREE_",),
    },
    "analytics_providers": {
        "segment": ("SEGMENT_",),
        "posthog": ("POSTHOG_",),
        "amplitude": ("AMPLITUDE_",),
        "mixpanel": ("MIXPANEL_",),
    },
    "feature_flag_providers": {
        "launchdarkly": ("LAUNCHDARKLY_", "LD_"),
        "unleash": ("UNLEASH_",),
        "flagsmith": ("FLAGSMITH_",),
        "growthbook": ("GROWTHBOOK_",),
    },
    "error_tracking": {
        "sentry": ("SENTRY_",),
        "rollbar": ("ROLLBAR_",),
        "bugsnag": ("BUGSNAG_",),
    },
    "metrics_and_monitoring": {
        "datadog": ("DATADOG_", "DD_"),
        "prometheus": ("PROMETHEUS_",),
        "new-relic": ("NEW_RELIC_", "NEWRELIC_"),
    },
    "tracing_and_otel": {
        "opentelemetry": ("OTEL_",),
        "honeycomb": ("HONEYCOMB_",),
    },
}


POLICY_PATTERNS = {
    "hosting_bias": {
        "self-hosted-preferred": ("self-hosted preferred", "self hosted preferred", "prefer self-hosted", "prefer self hosted"),
        "managed-services-discouraged": ("managed services discouraged", "avoid hosted saas", "no hosted saas", "avoid managed services"),
        "managed-services-allowed": ("hosted services allowed", "managed services allowed", "saas allowed", "hosted saas allowed"),
    },
    "license_constraints": {
        "oss-only": ("open source only", "oss only"),
        "copyleft-sensitive": ("avoid gpl", "copyleft sensitive", "no copyleft"),
        "commercial-allowed": ("commercial allowed", "paid services allowed"),
    },
    "compliance_hints": {
        "hipaa": ("hipaa",),
        "soc2": ("soc2", "soc 2"),
        "gdpr": ("gdpr",),
        "pci": ("pci", "pci-dss"),
        "fedramp": ("fedramp",),
        "pii-sensitive": ("pii", "personally identifiable"),
    },
    "stack_preferences": {
        "prefer-existing-stack": ("prefer existing stack", "reuse existing stack", "stay within the existing stack"),
        "avoid-second-tool-in-category": ("avoid second tool", "do not introduce a second", "keep one tool per category"),
        "no-new-infra-without-approval": ("no new infra without approval", "new infrastructure requires approval"),
    },
    "buy_vs_build_default": {
        "research-first": ("research build vs buy", "evaluate build vs buy", "compare vendors before implementation"),
        "build-first": ("build from scratch by default", "default to building in-house"),
    },
}


FEATURE_PATTERNS = {
    "background_jobs": {
        "keywords": ("background", "job", "queue", "worker", "async", "task", "scheduler", "cron"),
        "comparison_categories": ("retry_semantics", "worker_hosting_model", "scheduling", "queue_backend_fit"),
        "touchpoints": ("worker process model", "retry semantics", "queue/backend configuration"),
    },
    "search": {
        "keywords": ("search", "retrieval", "index", "indexing", "full-text", "full text", "vector", "semantic", "rag", "embeddings"),
        "comparison_categories": ("indexing_model", "relevance_tuning", "data_sync_complexity", "query_latency"),
        "touchpoints": ("indexing pipeline", "query API integration", "data backfill and sync"),
    },
    "auth": {
        "keywords": ("auth", "login", "sign-in", "signin", "signup", "identity", "oauth", "oidc", "sso", "permission", "rbac"),
        "comparison_categories": ("session_model", "user_migration", "compliance_support", "permissions_model"),
        "touchpoints": ("session model", "user data model", "permissions and middleware"),
    },
    "payments": {
        "keywords": ("payment", "billing", "checkout", "subscription", "invoice"),
        "comparison_categories": ("subscription_support", "tax_handling", "webhook_reliability", "finance_reporting"),
        "touchpoints": ("checkout flow", "billing data model", "webhook handling"),
    },
    "storage": {
        "keywords": ("upload", "file storage", "blob", "object storage", "media"),
        "comparison_categories": ("signed_url_support", "cdn_story", "access_control", "storage_cost_model"),
        "touchpoints": ("object lifecycle", "access control", "cdn and delivery"),
    },
    "email": {
        "keywords": ("email", "transactional email", "mail"),
        "comparison_categories": ("deliverability", "template_support", "webhook_events", "cost_per_volume"),
        "touchpoints": ("template rendering", "provider credentials", "event webhooks"),
    },
    "analytics": {
        "keywords": ("analytics", "events", "telemetry", "product analytics"),
        "comparison_categories": ("event_schema_governance", "warehouse_export", "cost_per_event", "privacy_controls"),
        "touchpoints": ("event schema", "client instrumentation", "data export"),
    },
    "feature_flags": {
        "keywords": ("feature flag", "experiment", "rollout", "a/b test", "ab test"),
        "comparison_categories": ("targeting_model", "evaluation_latency", "auditability", "self_hosting_option"),
        "touchpoints": ("flag evaluation path", "config rollout", "targeting data"),
    },
    "observability": {
        "keywords": ("monitoring", "tracing", "logging", "alerting", "error tracking"),
        "comparison_categories": ("signal_coverage", "instrumentation_burden", "alerting_fit", "cost_at_scale"),
        "touchpoints": ("telemetry instrumentation", "alert routing", "retention policy"),
    },
}


FAMILY_TO_TOOL_CATEGORIES = {
    "background_jobs": ("queues", "job_runtimes", "workflow_engines"),
    "search": ("search_engines", "vector_stores"),
    "auth": ("identity_providers", "auth_frameworks"),
    "payments": ("payment_providers",),
    "storage": ("object_storage",),
    "email": ("email_providers",),
    "analytics": ("analytics_providers",),
    "feature_flags": ("feature_flag_providers",),
    "observability": ("error_tracking", "metrics_and_monitoring", "tracing_and_otel"),
}


GENERAL_COMPARISON_CATEGORIES = (
    "fit_with_existing_stack",
    "implementation_time",
    "operational_burden",
    "integration_cost",
    "migration_risk",
    "lock_in_risk",
    "license_and_cost",
)
