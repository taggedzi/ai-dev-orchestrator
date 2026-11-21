FROM python:3.13.17-trixie@sha256:bf756c962c5d29f6fe30dbf70c692b1e978c272619e8f1096e1d697934c662bf AS builder
ENV PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_CONFIG_FILE=/dev/null \
    PYTHONDONTWRITEBYTECODE=1 SOURCE_DATE_EPOCH=1767225600
WORKDIR /inputs
COPY . /inputs/
RUN python /inputs/build_inside.py

FROM python:3.13.17-slim-trixie@sha256:d879ed88565a7a3c614b980b369d4a5025a9d057b71f93d09fc6d0b2ca823a18
ENV PATH=/opt/openhands/bin:/opt/runtime/bin:/usr/local/bin:/usr/bin:/bin \
    LD_LIBRARY_PATH=/opt/runtime/lib \
    HOME=/scratch/home USER=openhands LOGNAME=openhands \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 \
    OH_ENABLE_VSCODE=false OH_ENABLE_BROWSER=false \
    OH_CONVERSATION_RUNTIME=local OH_CONVERSATION_RUNTIME_SELECTABLE=false \
    OH_PRELOAD_TOOLS=false OH_MAX_CONCURRENT_RUNS=1 \
    OH_CONVERSATIONS_PATH=/state/conversations OH_BASH_EVENTS_DIR=/state/bash-events \
    OH_WORKSPACE_PATH=/workspace/project \
    DO_NOT_TRACK=1 OH_TELEMETRY_CONSENT=denied OH_TELEMETRY_CONSENT_MODE=override \
    OPENHANDS_BUILD_GIT_SHA=504a88cab0fb48ee5226238ad7b8f1d865fa84a8
COPY --from=builder /opt/openhands /opt/openhands
COPY --from=builder /opt/runtime /opt/runtime
COPY --from=builder /build-evidence /usr/share/mcli1-build
RUN python -c "import os,pathlib; p=pathlib.Path; assert 'openhands:' not in p('/etc/passwd').read_text(); p('/etc/passwd').open('a').write('openhands:x:10001:10001:fixture:/scratch/home:/bin/bash\n'); p('/etc/group').open('a').write('openhands:x:10001:\n'); [(p(d).mkdir(parents=True,exist_ok=True),os.chown(d,10001,10001)) for d in ['/scratch/home','/state','/workspace/project']]"
USER 10001:10001
WORKDIR /workspace/project
ENTRYPOINT ["/opt/runtime/bin/tini", "--", "/opt/openhands/bin/python", "-m", "openhands.agent_server"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
