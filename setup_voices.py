#!/usr/bin/env python3
"""
Quick test script to verify voices and start the room
"""

import subprocess
import sys
import os

def test_voices():
    """Test available edge-tts voices"""
    print("\nTesting voice synthesis...")
    print("-" * 40)
    
    try:
        import edge_tts
        import asyncio
        import tempfile
        
        voices = {
            "Alice": ("en-US-AriaNeural", "Hello, I'm Alice. I seek patterns in the chaos."),
            "Bob": ("en-US-GuyNeural", "Bob here. Let's ground this in reality."),
            "Charlie": ("en-US-JennyNeural", "Charlie speaking. Every word is jazz."),
            "Diana": ("en-US-SaraNeural", "This is Diana. I sense the spaces between."),
        }
        
        async def test_voice(name, voice, text):
            print(f"Testing {name}'s voice ({voice})...")
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tts = edge_tts.Communicate(text, voice)
                await tts.save(tmp.name)
                
                # Try to play it
                if sys.platform == "darwin":  # macOS
                    subprocess.run(["afplay", tmp.name])
                elif sys.platform.startswith("linux"):
                    # Try various Linux audio players
                    for player in ["mpg123", "mpv", "paplay", "aplay"]:
                        try:
                            subprocess.run([player, tmp.name], capture_output=True)
                            break
                        except FileNotFoundError:
                            continue
                elif sys.platform == "win32":
                    # Try mpv first (from chocolatey/scoop/etc)
                    played = False
                    mpv_paths = [
                        'mpv',  # In PATH
                        r'C:\ProgramData\chocolatey\bin\mpv.exe',
                        r'C:\tools\mpv\mpv.exe',
                        os.path.expanduser(r'~\scoop\apps\mpv\current\mpv.exe'),
                        os.path.expanduser(r'~\AppData\Local\Programs\mpv\mpv.exe'),
                    ]
                    
                    for mpv_path in mpv_paths:
                        try:
                            result = subprocess.run(
                                [mpv_path, '--really-quiet', '--no-video', tmp.name],
                                capture_output=True,
                                timeout=5
                            )
                            if result.returncode == 0:
                                played = True
                                print(f"  ✓ Played with mpv")
                                break
                        except:
                            continue
                    
                    if not played:
                        # Fallback to Windows Media Player
                        os.system(f'start /min wmplayer {tmp.name}')
                        print(f"  ✓ Played with Windows Media Player (fallback)")
                
                os.unlink(tmp.name)
        
        # Test each voice
        for name, (voice, text) in voices.items():
            asyncio.run(test_voice(name, voice, text))
            
        print("\nVoice test complete! If you heard the voices, you're ready.")
        
    except ImportError:
        print("edge-tts not installed. Install with: pip install edge-tts")
    except Exception as e:
        print(f"Voice test failed: {e}")

def list_all_voices():
    """List all available edge-tts voices"""
    print("\nAvailable voices:")
    print("-" * 60)
    
    try:
        result = subprocess.run(["edge-tts", "--list-voices"], capture_output=True, text=True)
        
        # Parse and show English voices
        lines = result.stdout.split('\n')
        english_voices = []
        
        for line in lines:
            if 'en-' in line.lower():
                parts = line.split(':')
                if len(parts) >= 2:
                    voice_name = parts[0].strip()
                    if voice_name.startswith('Name'):
                        voice_name = parts[1].strip()
                    if voice_name and not voice_name.startswith('Name'):
                        english_voices.append(voice_name)
        
        # Group by accent
        us_voices = [v for v in english_voices if 'en-US' in v]
        gb_voices = [v for v in english_voices if 'en-GB' in v]
        other_voices = [v for v in english_voices if 'en-US' not in v and 'en-GB' not in v]
        
        if us_voices:
            print("\nUS English voices:")
            for v in sorted(us_voices):
                print(f"  {v}")
                
        if gb_voices:
            print("\nUK English voices:")
            for v in sorted(gb_voices):
                print(f"  {v}")
                
        if other_voices:
            print("\nOther English voices:")
            for v in sorted(other_voices):
                print(f"  {v}")
                
        print("\nYou can modify VOICE_MAP in four_agents_room.py to use any of these.")
        
    except FileNotFoundError:
        print("edge-tts not found. Install with: pip install edge-tts")
    except Exception as e:
        print(f"Could not list voices: {e}")

if __name__ == "__main__":
    print("""
    ╔════════════════════════════════════════════════════════════╗
    ║              FOUR AGENTS - VOICE SETUP                     ║
    ╚════════════════════════════════════════════════════════════╝
    """)
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "test":
            test_voices()
        elif sys.argv[1] == "list":
            list_all_voices()
        else:
            print("Usage: python setup_voices.py [test|list]")
    else:
        print("Commands:")
        print("  python setup_voices.py test  - Test agent voices")
        print("  python setup_voices.py list  - List all available voices")
        print("\nTo start the room:")
        print("  python four_agents_room.py")
