import os
import requests
import socket
import threading
import time
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import streamlit as st
import uvicorn
from typing import Optional

# Initialize FastAPI app
app = FastAPI(title="GitHub Audio Access API")

# Configuration
GITHUB_RAW_BASE_URL = "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"
GITHUB_API_BASE_URL = "https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
AUDIO_CACHE_DIR = "audio_cache"
SUPPORTED_FORMATS = ('.mp3', '.wav', '.ogg', '.flac', '.m4a')
SERVER_START_TIMEOUT = 5  # seconds to wait for server to start

# Create cache directory if it doesn't exist
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)

class ServerManager:
    def __init__(self):
        self.port = None
        self.server_thread = None
        self.server_started = False

    def find_available_port(self, start_port: int = 8000) -> int:
        """Find an available port starting from start_port."""
        for port in range(start_port, start_port + 50):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('localhost', port))
                    return port
            except OSError:
                continue
        raise OSError(f"No available port found in range {start_port}-{start_port+49}")

    def start_server(self):
        """Start the FastAPI server in a separate thread."""
        if self.server_thread and self.server_thread.is_alive():
            return

        self.port = self.find_available_port()
        self.server_started = False

        def run_fastapi():
            uvicorn.run(app, host="0.0.0.0", port=self.port)

        self.server_thread = threading.Thread(target=run_fastapi, daemon=True)
        self.server_thread.start()

        # Wait for server to be ready
        start_time = time.time()
        while not self.server_started and time.time() - start_time < SERVER_START_TIMEOUT:
            try:
                response = requests.get(f"http://localhost:{self.port}/health")
                if response.status_code == 200:
                    self.server_started = True
            except:
                time.sleep(0.1)

    def is_server_running(self) -> bool:
        """Check if the server is running."""
        if not self.port:
            return False
        try:
            response = requests.get(f"http://localhost:{self.port}/health", timeout=1)
            return response.status_code == 200
        except:
            return False

# Create server manager instance
server_manager = ServerManager()

@app.get("/health")
async def health_check():
    """Health check endpoint for server status."""
    return {"status": "ok"}

@app.get("/audio/{owner}/{repo}/{branch}/{file_path:path}")
async def get_audio_file(owner: str, repo: str, branch: str, file_path: str):
    """FastAPI endpoint to access audio file from GitHub."""
    try:
        local_path = download_audio_from_github(owner, repo, branch, file_path)
        return FileResponse(local_path)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/list-audio/{owner}/{repo}/{branch}/{path:path}")
async def list_audio_files(owner: str, repo: str, branch: str, path: str):
    """FastAPI endpoint to list audio files in a GitHub directory."""
    api_url = GITHUB_API_BASE_URL.format(
        owner=owner,
        repo=repo,
        path=path.lstrip('/'),
        branch=branch
    )
    
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        contents = response.json()
        
        if not isinstance(contents, list):
            return JSONResponse(status_code=400, content={"error": "Path is not a directory"})
        
        audio_files = [
            item['name'] for item in contents 
            if isinstance(item, dict) and 
            item.get('type') == 'file' and 
            item.get('name', '').lower().endswith(SUPPORTED_FORMATS)
        ]
        
        return {"audio_files": audio_files}
    except requests.RequestException as e:
        return JSONResponse(status_code=404, content={"error": str(e)})

def download_audio_from_github(owner: str, repo: str, branch: str, file_path: str) -> str:
    """Download audio file from GitHub and save to local cache."""
    audio_url = GITHUB_RAW_BASE_URL.format(
        owner=owner,
        repo=repo,
        branch=branch,
        file_path=file_path.lstrip('/')
    )
    local_path = os.path.join(AUDIO_CACHE_DIR, os.path.basename(file_path))
    
    try:
        response = requests.get(audio_url)
        response.raise_for_status()
        
        with open(local_path, 'wb') as f:
            f.write(response.content)
            
        return local_path
    except requests.RequestException as e:
        raise HTTPException(status_code=404, detail=f"Audio file not found: {str(e)}")

def main():
    """Main application function with persistent state."""
    st.title("GitHub Audio File Access")
    st.markdown("Access and play audio files directly from a GitHub repository")
    
    # Initialize session state variables if they don't exist
    if 'audio_files' not in st.session_state:
        st.session_state.audio_files = []
    if 'selected_file' not in st.session_state:
        st.session_state.selected_file = None
    if 'repo_info' not in st.session_state:
        st.session_state.repo_info = {
            'owner': 'MEERAN2314',
            'repo': 'Audio_files-',
            'branch': 'main',
            'path': ''
        }
    
    # Start or restart server if needed
    if not server_manager.is_server_running():
        server_manager.start_server()
        time.sleep(1)  # Give server a moment to start
    
    if server_manager.port:
        st.info(f"Server running on port: {server_manager.port}")
    else:
        st.error("Server failed to start")
        return
    
    # Repository information form
    with st.form("repo_info_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            owner = st.text_input("GitHub Owner/Username", st.session_state.repo_info['owner'])
        with col2:
            repo = st.text_input("Repository Name", st.session_state.repo_info['repo'])
        with col3:
            branch = st.text_input("Branch", st.session_state.repo_info['branch'])
        
        path = st.text_input("Path to audio files (leave empty for root)", st.session_state.repo_info['path'])
        
        if st.form_submit_button("Update Repository Info"):
            st.session_state.repo_info = {
                'owner': owner,
                'repo': repo,
                'branch': branch,
                'path': path
            }
            st.session_state.audio_files = []  # Clear previous files
            st.session_state.selected_file = None  # Clear selection
            st.experimental_rerun()
    
    # List audio files button
    if st.button("List Audio Files"):
        try:
            with st.spinner("Fetching audio files..."):
                # Ensure server is running
                if not server_manager.is_server_running():
                    server_manager.start_server()
                    time.sleep(1)
                
                # Properly encode the path
                encoded_path = requests.utils.quote(st.session_state.repo_info['path'])
                list_url = f"http://localhost:{server_manager.port}/list-audio/" \
                          f"{st.session_state.repo_info['owner']}/" \
                          f"{st.session_state.repo_info['repo']}/" \
                          f"{st.session_state.repo_info['branch']}/" \
                          f"{encoded_path}"
                
                try:
                    response = requests.get(list_url, timeout=10)
                    
                    if response.status_code == 200:
                        st.session_state.audio_files = response.json().get("audio_files", [])
                        st.session_state.selected_file = None  # Reset selection when listing new files
                        st.success(f"Found {len(st.session_state.audio_files)} audio files")
                    else:
                        error_msg = response.json().get("error", "Unknown error")
                        st.error(f"Error fetching files: {error_msg}")
                except requests.exceptions.RequestException as e:
                    st.error(f"Connection error: {str(e)}. Trying to restart server...")
                    server_manager.start_server()
                    time.sleep(1)
                    st.experimental_rerun()
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
    
    # Display audio files if available
    if st.session_state.audio_files:
        selected_file = st.selectbox(
            "Select an audio file",
            st.session_state.audio_files,
            index=st.session_state.audio_files.index(st.session_state.selected_file) 
            if st.session_state.selected_file in st.session_state.audio_files 
            else 0
        )
        
        if selected_file != st.session_state.selected_file:
            st.session_state.selected_file = selected_file
            st.experimental_rerun()
        
        if st.session_state.selected_file:
            # Properly encode the file path
            file_path = f"{st.session_state.repo_info['path']}/{st.session_state.selected_file}" \
                      if st.session_state.repo_info['path'] else st.session_state.selected_file
            encoded_file_path = requests.utils.quote(file_path)
            audio_url = f"http://localhost:{server_manager.port}/audio/" \
                       f"{st.session_state.repo_info['owner']}/" \
                       f"{st.session_state.repo_info['repo']}/" \
                       f"{st.session_state.repo_info['branch']}/" \
                       f"{encoded_file_path}"
            
            st.audio(audio_url)
            
            try:
                st.download_button(
                    label="Download Audio",
                    data=requests.get(audio_url).content,
                    file_name=st.session_state.selected_file,
                    mime="audio/mpeg"
                )
            except Exception as e:
                st.error(f"Download failed: {str(e)}")

if __name__ == "__main__":
    # Initialize and start server
    server_manager.start_server()
    
    # Run main application
    main()