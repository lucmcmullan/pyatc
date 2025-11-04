from atc.objects.runway_v2 import all_runways
from atc.objects.aircraft_v2 import spawn_random_plane
from atc.radar import draw_radar, draw_performance_menu
from atc.utils import check_conflicts, calculate_layout
from atc.command_parser import CommandParser
from constants import WIDTH, HEIGHT, FPS, SIM_SPEED, ERROR_LOG_FILE
import pygame, sys, traceback, time
from collections import defaultdict

# v1.5.1

parser = CommandParser()

def handle_exception(exc_type, exc_value, exc_traceback):
    """Log uncaught exceptions instead of crashing."""
    global fatal_error
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    # Build formatted traceback
    error_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}]\n{error_text}\n{'-'*60}\n"

    # Write to file
    with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry)

    fatal_error = entry  # store to show in overlay later
    print("A fatal error occurred — logged to error_log.txt")

sys.excepthook = handle_exception

def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("PYATC")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 16)
    
    radio_log = defaultdict(list)
    active_cs = None
    selected_plane = None
    radio_scroll = 0

    runways = all_runways()
    planes = [spawn_random_plane(i) for i in range(1, 6)]

    input_str = ""
    cursor_pos = 0
    cursor_visible = True
    cursor_timer = 0
    messages = []

    global fatal_error
    fatal_error = None

    show_error_log = False
    show_perf = False

    running = True
    while running:
        if fatal_error:
            dt = 0
        else:
            dt = clock.tick(FPS) / 1000.0
            dt *= SIM_SPEED

        cursor_timer += dt
        if cursor_timer >= 2:
            cursor_visible = not cursor_visible
            cursor_timer = 0

        layout = calculate_layout(WIDTH, HEIGHT)
        font_size = layout["FONT_SIZE"]
        font = pygame.font.SysFont("Consolas", font_size)
        console_height = int(font_size * 2.2)
        bottom_y = HEIGHT - console_height + int(font_size * 0.5)

        for event in pygame.event.get(): # event handling section
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos

                if event.button == 1: # leftclick
                    for p in planes:
                        if (p.x - mx) ** 2 + (p.y - my) ** 2 < 10 ** 2:
                            selected_plane = p
                            active_cs = p.callsign
                            radio_scroll = 0
                            input_str = f"{p.callsign} " # append selected aircraft cs to input
                            cursor_pos = len(input_str)
                            break
                        else:
                            selected_plane = None   # reset selected plane if
                            active_cs = None        # mouse clicks off-plane
                            input_str = ""
                            cursor_pos = 0
                            
                elif event.button == 4: # scroll down
                    radio_scroll = max(0, radio_scroll - 1)

                elif event.button == 5: # scroll up
                    radio_scroll += 1
                    
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN: # send input command
                    if input_str.strip():
                        results = parser.parse(input_str, planes)
                        messages.append("> " + input_str)

                        if isinstance(results, list):
                            segments = [seg.strip() for seg in input_str.split("|") if seg.strip()] # parse command based on | position
                            for res in results:
                                cs = res["callsign"]
                                ctrl_msg = res["ctrl_msg"]
                                ack_msg = res["ack_msg"]

                                messages.append(ctrl_msg)

                                if cs not in radio_log:
                                    radio_log[cs] = []

                                cs_segment = next((seg for seg in segments if seg.startswith(cs)), input_str)

                                radio_log[cs].append(f"CTRL: {cs_segment}")
                                radio_log[cs].append(f"{cs}: {ack_msg}")
                        else:
                            ctrl_msg, ack_msg = results # legacy fallback for chained commands
                            messages.append(ctrl_msg)
                            parts = input_str.strip().upper().split()
                            if parts:
                                cs = parts[0]
                                radio_log[cs].append(f"CTRL: {input_str}")
                                radio_log[cs].append(f"{cs}: {ack_msg}")

                        input_str = ""
                        cursor_pos = 0

                elif event.key == pygame.K_BACKSPACE: 
                    if cursor_pos > 0:
                        input_str = input_str[:cursor_pos - 1] + input_str[cursor_pos:]
                        cursor_pos -= 1

                elif event.key == pygame.K_DELETE: 
                    if cursor_pos < len(input_str):
                        input_str = input_str[:cursor_pos] + input_str[cursor_pos + 1:]

                elif event.key == pygame.K_LEFT: 
                    cursor_pos = max(0, cursor_pos - 1)

                elif event.key == pygame.K_RIGHT: 
                    cursor_pos = min(len(input_str), cursor_pos + 1)

                elif event.key == pygame.K_F3:
                    show_perf = not show_perf

                elif event.key == pygame.K_F9:
                    show_error_log = not show_error_log

                else:
                    if event.unicode.isprintable():
                        input_str = input_str[:cursor_pos] + event.unicode.upper() + input_str[cursor_pos:]
                        cursor_pos += 1

        try:
            for plane in planes:
                plane.update(dt)
        except Exception:
            handle_exception(*sys.exc_info())
        
        conflicts = check_conflicts(planes)

        draw_radar(screen, planes, font, messages, 
                   conflicts, radio_log=radio_log, active_cs=active_cs, 
                   selected_plane=selected_plane, radio_scroll=radio_scroll, 
                   runways=runways)

        if show_error_log and fatal_error:
            surf = pygame.Surface((WIDTH - 100, HEIGHT - 100), pygame.SRCALPHA)
            surf.fill((20, 0, 0, 220))
            y = 20

            lines = fatal_error.splitlines() if isinstance(fatal_error, str) else []
            for line in lines[-30:]:
                txt = font.render(line, True, (255, 100, 100))
                surf.blit(txt, (20, y))
                y += 18
                if y > HEIGHT - 150:
                    break

            screen.blit(surf, (50, 50))
            header = font.render("FATAL ERROR — PRESS F9 TO HIDE", True, (255, 255, 0))
            screen.blit(header, (60, 60))

        if show_perf:
            draw_performance_menu(screen, font, clock, planes, runways, SIM_SPEED)
            
        pygame.draw.rect(screen, (20, 20, 20), (0, HEIGHT - console_height, WIDTH, console_height))
        
        prompt = "> " + input_str
        txt = font.render(prompt, True, (255, 255, 255))
        prompt_x = int(font_size * 0.5)
        screen.blit(txt, (prompt_x, bottom_y))

        # --- Draw blinking cursor ---
        if cursor_visible:
            # measure text width up to cursor position
            cursor_text = font.render("> " + input_str[:cursor_pos], True, (255, 255, 255))
            cursor_x = prompt_x + cursor_text.get_width()
            cursor_y = bottom_y
            pygame.draw.rect(screen, (255, 255, 255),
                            (cursor_x, cursor_y - 2, 2, font.get_height()))

        pygame.display.flip()

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()