ARG NODE_IMAGE=node:22-alpine
ARG NGINX_IMAGE=nginx:1.27-alpine
FROM ${NODE_IMAGE} AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ENV VITE_API_BASE=/api/v1
ENV CI=true
RUN npm run build

FROM ${NGINX_IMAGE}
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /opt/traffic-console/html
COPY public/runtime-config.template.js /opt/traffic-console/html/runtime-config.template.js
COPY docker-entrypoint.d/40-amap-runtime-config.sh /docker-entrypoint.d/50-console-runtime-config.sh
RUN chmod 755 /opt /opt/traffic-console \
    && find /opt/traffic-console/html -type d -exec chmod 755 {} \; \
    && find /opt/traffic-console/html -type f -exec chmod 644 {} \; \
    && chmod 755 /docker-entrypoint.d/50-console-runtime-config.sh \
    && su nginx -s /bin/sh -c 'test -r /opt/traffic-console/html/index.html && test -x /opt/traffic-console/html/assets'
ENV AMAP_JS_API_KEY=""
ENV AMAP_SECURITY_JS_CODE=""
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
