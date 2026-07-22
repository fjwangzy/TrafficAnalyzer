FROM node:22-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ENV VITE_API_BASE=/api/v1
ENV CI=true
RUN npm run build

FROM nginx:1.27-alpine
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
COPY public/runtime-config.template.js /usr/share/nginx/html/runtime-config.template.js
COPY docker-entrypoint.d/40-amap-runtime-config.sh /docker-entrypoint.d/40-amap-runtime-config.sh
RUN chmod +x /docker-entrypoint.d/40-amap-runtime-config.sh
ENV AMAP_JS_API_KEY=""
ENV AMAP_SECURITY_JS_CODE=""
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
