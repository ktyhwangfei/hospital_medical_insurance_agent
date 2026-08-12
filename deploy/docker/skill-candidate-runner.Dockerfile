FROM python:3.12.11-alpine3.22

RUN addgroup -S candidate && adduser -S -G candidate -u 10001 candidate
COPY deploy/docker/skill_candidate_runner.py /opt/skill-candidate-runner.py
USER 10001:10001
ENTRYPOINT ["python", "-I", "/opt/skill-candidate-runner.py"]
