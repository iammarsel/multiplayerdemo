import pygame
import socket
import threading
import pickle
import math
import sys
import time

WIDTH, HEIGHT = 800, 600

players = {}  # {pid: {"pos":(x,y), "color":(r,g,b), "health":int, "kills":int, "is_dead":bool, ...}, ...}
bullets = []
my_id = None

HOST = "127.0.0.1"
PORT = 5555
client_socket = None

lock = threading.Lock()

# We'll track time_left from the server to display a countdown
time_left = 300  # default 5 minutes if not started

# For movement
move_speed = 5
dx = 0
dy = 0

pygame.init()
font = pygame.font.SysFont(None, 36)  # for on-screen text (timer, scoreboard, etc.)

def receive_data():
    global players, bullets, time_left

    while True:
        try:
            data = client_socket.recv(4096)
            if not data:
                break
            msg = pickle.loads(data)

            # Special messages (server_full, handshake, etc.)
            if "action" in msg:
                if msg["action"] == "server_full":
                    print("Server is full. Exiting.")
                    pygame.quit()
                    sys.exit()

            # Normal game state broadcast
            if "players" in msg and "bullets" in msg:
                with lock:
                    players = msg["players"]
                    bullets = msg["bullets"]
                    time_left = msg.get("time_left", 300)

        except:
            break

def send_to_server(message_dict):
    try:
        data = pickle.dumps(message_dict)
        client_socket.sendall(data)
    except:
        pass

def draw_leaderboard(screen):
    """
    Draw a simple leaderboard in the top-right corner,
    listing all players by kills descending, or by ID for a simpler approach.
    """
    # Sort players by kills descending
    sorted_players = sorted(players.items(), key=lambda p: p[1]["kills"], reverse=True)
    # Start from some top-right position
    x_start = WIDTH - 200
    y_start = 20
    line_height = 30

    label = font.render("Leaderboard", True, (255,255,255))
    screen.blit(label, (x_start, y_start))
    y_offset = y_start + line_height

    for pid, pdata in sorted_players:
        kills = pdata["kills"]
        text_str = f"Player {pid}: {kills} kills"
        text_surf = font.render(text_str, True, (255, 255, 255))
        screen.blit(text_surf, (x_start, y_offset))
        y_offset += line_height

def draw_timer(screen):
    """
    Draw the countdown timer in the top-left corner.
    """
    minutes = int(time_left // 60)
    seconds = int(time_left % 60)
    timer_str = f"{minutes:02d}:{seconds:02d}"
    text_surf = font.render(timer_str, True, (255, 255, 255))
    screen.blit(text_surf, (20, 20))

def main():
    global client_socket, my_id, dx, dy

    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.connect((HOST, PORT))
    client_socket.setblocking(True)

    # Receive initial handshake
    initial_data = client_socket.recv(4096)
    handshake = pickle.loads(initial_data)

    if handshake.get("action") == "server_full":
        print("Server is full. Exiting.")
        client_socket.close()
        return

    if handshake.get("action") == "handshake":
        my_id = handshake.get("player_id")
        print(f"[HANDSHAKE] My ID is {my_id}")
    else:
        print("Did not receive a proper handshake. Exiting.")
        client_socket.close()
        return

    # Start background thread to get updates
    threading.Thread(target=receive_data, daemon=True).start()

    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Multiplayer Shooter with Timer & Leaderboard")

    clock = pygame.time.Clock()

    running = True
    while running:
        clock.tick(60)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            # If we're dead, skip movement and shooting
            if my_id in players and players[my_id].get("is_dead"):
                continue

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_w:
                    dy = -move_speed
                elif event.key == pygame.K_s:
                    dy = move_speed
                elif event.key == pygame.K_a:
                    dx = -move_speed
                elif event.key == pygame.K_d:
                    dx = move_speed

                if event.key == pygame.K_SPACE:
                    # Shoot
                    mouse_x, mouse_y = pygame.mouse.get_pos()
                    with lock:
                        if my_id in players:
                            px, py = players[my_id]["pos"]
                        else:
                            px, py = (WIDTH//2, HEIGHT//2)

                    dir_x = mouse_x - px
                    dir_y = mouse_y - py
                    length = math.hypot(dir_x, dir_y)
                    if length != 0:
                        dir_x /= length
                        dir_y /= length

                    send_to_server({
                        "action": "shoot",
                        "player_id": my_id,
                        "dx": dir_x,
                        "dy": dir_y
                    })

            if event.type == pygame.KEYUP:
                if event.key in (pygame.K_w, pygame.K_s):
                    dy = 0
                if event.key in (pygame.K_a, pygame.K_d):
                    dx = 0

        # Send movement if alive
        with lock:
            if my_id in players and not players[my_id]["is_dead"]:
                if dx != 0 or dy != 0:
                    send_to_server({
                        "action": "move",
                        "player_id": my_id,
                        "dx": dx,
                        "dy": dy
                    })

        screen.fill((30, 30, 30))

        # Draw countdown timer (top-left)
        draw_timer(screen)

        # Draw leaderboard (top-right)
        draw_leaderboard(screen)

        with lock:
            # Draw players
            for pid, pdata in players.items():
                px, py = pdata["pos"]
                color = pdata["color"]
                health = pdata["health"]
                is_dead = pdata["is_dead"]

                # If dead, optionally skip drawing the player, or draw them differently
                if is_dead:
                    # Let's not draw a dead player at all
                    continue

                # Draw the player's 20x20 rect
                
                # spawn each player's image
                pygame.draw.rect(screen, color, (px - 10, py - 10, 20, 20))

                # Health bar above the player
                
                # instead of health rectangles we have health images
                bar_width = 20
                bar_height = 5
                health_ratio = max(0, health) / 100.0
                pygame.draw.rect(screen, (0, 255, 0),
                                 (px - 10, py - 20, int(bar_width * health_ratio), bar_height))
                # Red background for missing portion
                pygame.draw.rect(screen, (255, 0, 0),
                                 (px - 10 + int(bar_width * health_ratio),
                                  py - 20,
                                  int(bar_width * (1 - health_ratio)),
                                  bar_height))

            # Draw bullets
            
            # bullet custom images 
            for b in bullets:
                bx, by = b["x"], b["y"]
                pygame.draw.rect(screen, (255, 0, 0), (bx - 4, by - 4, 8, 8))

            # If we're dead, show the gray box with "YOU DIED!"
            if my_id in players and players[my_id]["is_dead"]:
                dead_surf = font.render("YOU DIED!", True, (255, 0, 0))
                rect = dead_surf.get_rect(center=(WIDTH//2, HEIGHT//2))
                screen.blit(dead_surf, rect)

        pygame.display.flip()

    pygame.quit()
    client_socket.close()

if __name__ == "__main__":
    main()
