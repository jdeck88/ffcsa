FROM node:15.9.0
WORKDIR /app
# COPY ../package.json .
COPY ../ .
RUN npm install

CMD ["npm", "run", "dev"]