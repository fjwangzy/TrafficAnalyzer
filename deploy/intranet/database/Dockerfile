ARG DATABASE_BASE_IMAGE
FROM ${DATABASE_BASE_IMAGE}
USER root
# Core PostGIS is sufficient for project geometry; raster/GDAL and SFCGAL are unused.
RUN apk add --no-cache geos proj libxml2 json-c protobuf-c libstdc++ pcre2 \
    && apk add --no-cache --virtual .postgis-build build-base autoconf automake libtool gettext-dev \
       geos-dev proj-dev libxml2-dev json-c-dev protobuf-c-dev pcre2-dev $DOCKER_PG_LLVM_DEPS \
    && wget -O /tmp/postgis.tar.gz https://github.com/postgis/postgis/archive/3.6.4.tar.gz \
    && echo '4f80e1a4d227f088ae818f79180debd5894c075615823e0f556f73479cf1f200  /tmp/postgis.tar.gz' | sha256sum -c - \
    && mkdir /tmp/postgis \
    && tar -xzf /tmp/postgis.tar.gz --strip-components=1 -C /tmp/postgis \
    && cd /tmp/postgis && ./autogen.sh \
    && ./configure --without-raster --without-sfcgal \
    && make -j2 && make install \
    && cd / && rm -rf /tmp/postgis /tmp/postgis.tar.gz \
    && apk del .postgis-build \
    && apk info -v > /database-dependencies.txt
COPY deploy/intranet/database/init-extensions.sh /docker-entrypoint-initdb.d/010_project.sh
ENV NO_TS_TUNE=true TIMESCALEDB_TELEMETRY=off
