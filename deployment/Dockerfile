FROM golang:1.26.10-bookworm@sha256:632dff7351799a5a9954a48dc06670ade72ee44e8c351cdc0e5a57af2fea21af AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential python3 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY stack.lock.json build_linux.py source_manifest.py ./
COPY .sources/ .sources/
RUN python3 build_linux.py
COPY gateway/ gateway/
RUN cd gateway && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOAMD64=v1 go build -trimpath -o /out/cpa-gateway .

FROM debian:bookworm-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tzdata curl && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/ /opt/cpa/
WORKDIR /data
EXPOSE 8317
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD curl --fail --silent http://127.0.0.1:8317/ >/dev/null || exit 1
CMD ["/opt/cpa/cli-proxy-api", "-config", "/data/config.yaml"]
