# nginx-unprivileged runs as a non-root user on port 8080 (helps with rule #2 later)
FROM nginxinc/nginx-unprivileged:1.27.0-alpine
COPY app/ /usr/share/nginx/html/
EXPOSE 8080
