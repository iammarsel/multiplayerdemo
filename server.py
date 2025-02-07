import socket
import threading
import pickle
import time
import random

HOST = "127.0.0.1"
PORT = 5555
MAX_PLAYERS = 5

# Each player's data:
# players[player_id] = {
#   "pos": (x, y),
#   "color": (r, g, b),
#   "health": int,
#   "kills": int,
#   "is_dead": bool,
#   "respawn_time": float  (timestamp when they'll respawn),
# }
players = {}
# bullets: list of dicts: { "x": float, "y": float, "dx": float, "dy": float, "owner_id": int }
bullets = []
next_player_id = 0

client_sockets = []
player_connections = {}  # map player_id -> socket for direct messages

# Game timer: starts (5 minutes = 300s) once we have at least 2 players
game_start_time = None
GAME_DURATION = 300  # 5 minutes in seconds

# A lock for thread-safe updates
lock = threading.Lock()

def handle_client(conn, addr, player_id):
    """Receive data from the client and update global state accordingly."""
    print(f"[NEW CONNECTION] Player {player_id} connected from {addr}")
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break

            try:
                msg = pickle.loads(data)
            except:
                continue

            with lock:
                action = msg.get("action")
                pid = msg.get("player_id")  # Which client sent it

                # Ignore commands from a dead player
                if pid in players and players[pid]["is_dead"]:
                    continue

                if action == "move":
                    dx = msg.get("dx", 0)
                    dy = msg.get("dy", 0)
                    if pid in players:
                        px, py = players[pid]["pos"]
                        players[pid]["pos"] = (px + dx, py + dy)

                elif action == "shoot":
                    dx = msg.get("dx", 0)
                    dy = msg.get("dy", 0)
                    if pid in players:
                        px, py = players[pid]["pos"]
                        bullet_speed = 10
                        bullets.append({
                            "x": px,
                            "y": py,
                            "dx": dx * bullet_speed,
                            "dy": dy * bullet_speed,
                            "owner_id": pid
                        })
    except Exception as e:
        print(f"[EXCEPTION] {e}")
    finally:
        with lock:
            if player_id in players:
                del players[player_id]
            if conn in client_sockets:
                client_sockets.remove(conn)
            if player_id in player_connections:
                del player_connections[player_id]

        conn.close()
        print(f"[DISCONNECT] Player {player_id} disconnected")

def broadcast_game_state():
    """
    Sends the entire game state (players, bullets) plus
    the countdown timer (time_left) to all clients.
    """
    global game_start_time
    # Calculate time_left if we have at least 2 players and the timer started
    if game_start_time is not None:
        elapsed = time.time() - game_start_time
        time_left = max(0, GAME_DURATION - elapsed)
    else:
        time_left = GAME_DURATION  # or just 0, if you prefer not showing a timer until it starts

    game_state = {
        "players": players,   # includes positions, colors, health, kills, is_dead, etc.
        "bullets": bullets,
        "time_left": time_left
    }
    data = pickle.dumps(game_state)

    for cs in client_sockets:
        try:
            cs.sendall(data)
        except:
            pass

def send_msg_to_player(pid, msg_dict):
    """
    Send a specific dictionary message to one player (if connected).
    """
    if pid in player_connections:
        try:
            player_connections[pid].sendall(pickle.dumps(msg_dict))
        except:
            pass

def check_bullet_collisions():
    """
    For each bullet, check if it collides with any *alive* player (besides its owner).
    If collision: reduce health by 25. If health <= 0 -> record a kill, set dead status, schedule respawn.
    Remove the bullet on collision (no piercing).
    """
    global bullets

    surviving_bullets = []

    for b in bullets:
        bx, by = b["x"], b["y"]
        owner_id = b["owner_id"]
        hit_something = False

        for pid, pdata in list(players.items()):
            if pid == owner_id or pdata["is_dead"]:
                continue  # skip the bullet's owner and dead players

            # bullet bounding box = (bx-4, by-4, 8x8)
            bullet_left = bx - 4
            bullet_right = bx + 4
            bullet_top = by - 4
            bullet_bottom = by + 4

            # player bounding box = (px-10, py-10, 20x20)
            px, py = pdata["pos"]
            player_left = px - 10
            player_right = px + 10
            player_top = py - 10
            player_bottom = py + 10

            if (bullet_right >= player_left and
                bullet_left <= player_right and
                bullet_bottom >= player_top and
                bullet_top <= player_bottom):
                # We have a collision
                pdata["health"] -= 25
                hit_something = True

                if pdata["health"] <= 0:
                    # Owner gets a kill
                    if owner_id in players:
                        players[owner_id]["kills"] += 1

                    # Mark victim as dead, set 5s respawn
                    pdata["is_dead"] = True
                    pdata["health"] = 0  # just to be sure

                break

        if not hit_something:
            surviving_bullets.append(b)

    bullets = surviving_bullets

def game_loop():
    """
    Continually update bullets, collisions, respawns, and broadcast updates.
    """
    global bullets
    while True:
        time.sleep(0.03)  # ~33 updates per second
        with lock:
            # Move bullets
            for b in bullets:
                b["x"] += b["dx"]
                b["y"] += b["dy"]

            # Remove out-of-bounds bullets
            bullets = [
                b for b in bullets
                if 0 <= b["x"] <= 800 and 0 <= b["y"] <= 600
            ]

            # Check collisions
            check_bullet_collisions()

            # Broadcast state
            broadcast_game_state()

def main():
    global next_player_id, client_sockets, player_connections
    global game_start_time

    print("[STARTING] Server is starting...")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[LISTENING] Server is listening on {HOST}:{PORT}")

    threading.Thread(target=game_loop, daemon=True).start()

    while True:
        conn, addr = server.accept()
        conn.setblocking(True)

        with lock:
            if len(players) >= MAX_PLAYERS:
                # Server is full
                msg = {"action": "server_full"}
                conn.sendall(pickle.dumps(msg))
                conn.close()
                continue

            # Assign new ID
            player_id = next_player_id
            next_player_id += 1

            color = (
                random.randint(50, 255),
                random.randint(50, 255),
                random.randint(50, 255)
            )

            # Initialize the new player
            players[player_id] = {
                "pos": (400, 300), # random between  50 too 950 for x and 600 to 700 for y
                "color": color, # equipped skin
                "health": 100,
                "kills": 0,
                "is_dead": False,
            }

            client_sockets.append(conn)
            player_connections[player_id] = conn

            # If we now have at least 2 players, and the timer hasn't started, start it
            if game_start_time is None and len(players) >= 4:
                game_start_time = time.time()

        # Send handshake
        handshake_msg = {
            "action": "handshake",
            "player_id": player_id,
            "max_players": MAX_PLAYERS
        }
        conn.sendall(pickle.dumps(handshake_msg))

        # Spawn thread for this client
        t = threading.Thread(target=handle_client, args=(conn, addr, player_id), daemon=True)
        t.start()

if __name__ == "__main__":
    main()
