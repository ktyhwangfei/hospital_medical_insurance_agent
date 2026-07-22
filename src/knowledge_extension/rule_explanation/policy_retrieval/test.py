from pymilvus import connections, Collection

connections.connect(host="127.0.0.1", port="19530")

col = Collection("policy_facts")
col.load()

rows = col.query(
    expr='fact_type != ""',
    limit=5,
    output_fields=[
        "fact_id",
        "fact_type",
        "population",
        "service_type",
        "hospital_level",
        "admission_order",
        "evidence_text",
    ],
)

for r in rows:
    print(r)