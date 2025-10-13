# Contributing 

1. Clone the repository.
2. Checkout the `develop` branch: `git checkout develop`.
3. **Create** a `docker-compose.override.yml` with the following contents:
   ```yaml
   services:
     sonobarr:
       build:
         context: .
         dockerfile: Dockerfile
         network: host
       image: sonobarr-local
       volumes:
         - ./config:/sonobarr/config
         - /etc/localtime:/etc/localtime:ro
         - ./src:/sonobarr/src
       #ports:
       #  - "5000:5000"
       networks:
         npm_proxy:
           ipv4_address: 192.168.97.23 #change as you need

   networks:
     npm_proxy:
       external: true
   ```
4. Build the image with `sudo docker compose up -d` - later this will re-use the local image.
5. Make code changes in `src/` or other required files.
6. Test the changes by restarting the docker image `sudo docker compose down && sudo docker compose up -d` and clearing cache in browser.
7. Once ready to commit, make sure the build still works as well `sudo docker compose down -v --remove-orphans && sudo docker system prune -a --volumes -f && sudo docker compose up -d`.
8. Commit your work to the `develop` branch.

**Always test your changes with at least two accounts - admin and a common user - in the app, in at least two distinct browser builds (such as safari and chrome, for example).**
**Remember that if you made changes affecting config (that is, database or configuration) you have to delete the `./config` folder before rebuilding or restarting the app.
