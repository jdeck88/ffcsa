FROM node:15.9.0
WORKDIR /app
# COPY package.json .
# COPY . .

COPY package.json ./package.json
COPY tailwind.config.js ./tailwind.config.js
COPY webpack.config.js ./webpack.config.js

RUN npm install

CMD ["npm", "run", "dev"]