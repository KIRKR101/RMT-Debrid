# RMT-Debrid
A simple web interface to a flask server which takes a magnet link to download a file to the host machine. Aria2 is used to execute the downloads.

## Requirements
- Python
- Pip
- Aria2
- (Real-Debrid API key)[https://real-debrid.com/apitoken]

## Usage
1. Make sure you have a running Aria2 server
  	1. `aria2c --enable-rpc --rpc-listen-all=true --rpc-allow-origin-all=true --no-conf`
  
2. Clone this repository with Git & install requirements
  	1. `git clone https://github.com/KIRKR101/RMT-Debrid.git`
  	2. `cd RMT-Debrid`
  	3. `pip install requirements.txt`

3. Rename the `.env.sample` to `.env`, and replace its contents with your actual (API key)[https://real-debrid.com/apitoken] and download path. For Windows, use double backwards slashes, e.g. "C:\\Users\\user\\Downloads".
     
4. Run the app
	1. `python app.py`

5. Access the page through http://127.0.0.1:5000/

- To access from another device, upon up the port, or, so it can serve as an actual remote (from outside the LAN), use a reverse proxy like NGINX, or, simpler: Cloudflare Tunnels.

- You can add links through the main page, and view their progress from there. You can also add previously cached torrents to be marked for download.

![Home Page](https://github.com/user-attachments/assets/27577ffb-400f-453c-bd3f-cbba733554ab)
