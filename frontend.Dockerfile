FROM node:15.9.0
RUN mkdir -p /app
WORKDIR /app
COPY package.json .
COPY . .

# Create a nonroot user, and switch to it
RUN /usr/sbin/useradd --create-home --home-dir /usr/local/nonroot --shell /bin/bash nonroot 

RUN chown -R nonroot /app

# Switch to our nonroot user
USER nonroot


RUN npm install

# run with npm
CMD ["npm", "run", "dev"]