FROM golang:1.26-bookworm@sha256:a688600ca24f8a4d3ca77f95b0dd40704a9fc787c826660eb7ba0b641b8b175d AS build
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
