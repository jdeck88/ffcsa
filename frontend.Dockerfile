FROM node:15.9.0
RUN mkdir -p /app
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .

CMD ["npm", "run", "dev"]