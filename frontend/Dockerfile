# MediRail 웹 (정적 빌드 → nginx). 빌드 컨텍스트는 frontend/ 다.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# API 주소는 빌드 시점에 번들에 들어간다 (Railway 변수 VITE_API_URL이 build arg로 전달됨)
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:1.27-alpine
# /etc/nginx/templates/*.template 은 컨테이너 시작 시 환경변수(PORT)가 치환되어 conf.d로 들어간다
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV PORT=8080
EXPOSE 8080
