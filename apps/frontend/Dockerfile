FROM docker.io/library/node:22.23.3-alpine3.24 AS build

WORKDIR /app

COPY apps/frontend/package.json apps/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY apps/frontend/ ./
RUN npm run build

FROM docker.io/nginxinc/nginx-unprivileged:1.31.6-alpine3.24

COPY apps/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]