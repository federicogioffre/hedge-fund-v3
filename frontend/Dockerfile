# Hedge Fund V7 frontend: Vite + React + TypeScript + Tailwind
FROM node:20-alpine

WORKDIR /app

# Install deps first for better layer caching
COPY package.json ./
RUN npm install --no-audit --no-fund

# Copy source
COPY . .

EXPOSE 5173

# Dev server by default (hot reload). For production override with:
#   CMD ["npm", "run", "build"] + nginx layer.
CMD ["npm", "run", "dev"]
