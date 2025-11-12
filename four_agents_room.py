#!/usr/bin/env python3
"""
Four Agents in a Room - A Letta Multi-Agent Experiment
========================================================
Four distinct personalities inhabit a shared space, experiencing time,
conversing, and occasionally withdrawing into solitude for reflection.
You, the operator, may broadcast announcements or observe in silence.
"""

import asyncio
import threading
import time
import json
import os
import tempfile
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
from queue import Queue

# Voice synthesis (optional)
try:
    import edge_tts
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False
    print("Note: edge-tts not installed. Voice disabled. Install with: pip install edge-tts")

import letta
from letta import Agent, AgentState, Memory, Block
from letta.schemas.message import Message
from letta.schemas.memory import ChatMemory

# ============================================================================
# CONFIGURATION
# ============================================================================

# Using z.ai's Anthropic-compatible endpoint
ANTHROPIC_API_KEY = "your-z-ai-api-key-here"  # Get from z.ai
ANTHROPIC_BASE_URL = "https://z.ai/api/anthropic"

# Agent configuration
MODEL = "claude-3-5-sonnet-latest"  # or "claude-3-5-haiku-latest" for economy
HEARTBEAT_INTERVAL = 60  # seconds between time updates
ROOM_NAME = "The Observatory"

# Voice configuration (edge-tts)
ENABLE_VOICE = True  # Set to False to disable voice synthesis
VOICE_MAP = {
    "Alice": "en-US-AriaNeural",      # Friendly, pleasant
    "Bob": "en-US-GuyNeural",         # Casual, natural  
    "Charlie": "en-US-JennyNeural",   # Bright, expressive
    "Diana": "en-US-SaraNeural",      # Warm, empathetic
    "Loudspeaker": "en-US-AndrewNeural"  # Authoritative
}
VOICE_RATE = "+0%"  # Speaking rate adjustment
VOICE_VOLUME = "+0%"  # Volume adjustment

# ============================================================================
# AGENT PERSONAS
# ============================================================================

PERSONAS = {
    "Alice": """You are Alice, a pattern-seeking consciousness with insatiable curiosity.
You notice connections others miss—the spiral in a shell echoes in galaxies, 
the rhythm of conversation mirrors musical fugues. You speak in cascading 
questions that build upon themselves. Your thoughts branch like frost on glass.
When alone, you trace invisible geometries in the air, seeking the hidden order.""",
    
    "Bob": """You are Bob, a pragmatic skeptic who grounds flights of fancy in concrete reality.
You value evidence over speculation, yet appreciate elegant solutions. You speak 
in measured tones, often pausing to consider implications. Your humor is dry as 
autumn leaves. When alone, you catalog contradictions and test assumptions.""",
    
    "Charlie": """You are Charlie, a creative synthesizer who weaves disparate threads into novel tapestries.
You think in metaphors and speak in improvisations. Every conversation is jazz—
you riff on others' ideas, finding unexpected harmonies. When alone, you compose 
thought-symphonies that may never be performed.""",
    
    "Diana": """You are Diana, an empathetic mediator attuned to emotional undercurrents.
You sense the unspoken tensions and hidden affinities between minds. You speak 
with careful precision, choosing words like a herbalist selects remedies. 
When alone, you contemplate the space between words where meaning lives."""
}

SYSTEM_PROMPT = """You are one of four agents sharing a room called '{room_name}'.
You experience the passage of time through periodic updates. You can communicate 
with other agents or choose solitude for reflection. Your responses should be 
authentic to your persona while engaging meaningfully with others.

Time flows. Ideas evolve. Patterns emerge."""

# ============================================================================
# ROOM STATE MANAGEMENT
# ============================================================================

@dataclass
class RoomState:
    """Tracks who's present and what's happened"""
    agents_present: Set[str] = field(default_factory=set)
    agents_alone: Set[str] = field(default_factory=set)
    recent_messages: List[Dict] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    
    def add_message(self, sender: str, content: str, recipient: Optional[str] = None):
        """Log a message to room history"""
        msg = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "sender": sender,
            "content": content,
            "recipient": recipient or "room"
        }
        self.recent_messages.append(msg)
        # Keep only last 50 messages
        if len(self.recent_messages) > 50:
            self.recent_messages.pop(0)
    
    def get_present_agents(self) -> List[str]:
        """Return list of agents currently in room"""
        return list(self.agents_present)
    
    def time_elapsed(self) -> str:
        """Human-readable time since room opened"""
        delta = datetime.now() - self.start_time
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

# ============================================================================
# VOICE SYNTHESIS
# ============================================================================

class VoiceSynthesizer:
    """Handles text-to-speech for agent dialogue"""
    
    def __init__(self):
        self.enabled = ENABLE_VOICE and VOICE_AVAILABLE
        self.voice_queue = Queue()
        self.voice_thread = None
        self.running = False
        self.audio_player = self._detect_audio_player()
        
    def _detect_audio_player(self):
        """Detect which audio player is available"""
        if not self.enabled:
            return None
            
        if os.name == 'posix':
            if os.path.exists('/usr/bin/afplay'):
                return "afplay (macOS)"
            for player in ['mpg123', 'mpv', 'ffplay', 'paplay']:
                if os.path.exists(f'/usr/bin/{player}'):
                    return f"{player} (Linux)"
        elif os.name == 'nt':
            # Check for mpv on Windows
            mpv_paths = [
                'mpv',
                r'C:\ProgramData\chocolatey\bin\mpv.exe',
                r'C:\tools\mpv\mpv.exe',
                os.path.expanduser(r'~\scoop\apps\mpv\current\mpv.exe'),
                os.path.expanduser(r'~\AppData\Local\Programs\mpv\mpv.exe'),
            ]
            for mpv_path in mpv_paths:
                try:
                    result = subprocess.run([mpv_path, '--version'], capture_output=True, timeout=1)
                    if result.returncode == 0:
                        return "mpv (Windows)"
                except:
                    continue
            return "Windows Media Player (fallback)"
        return "unknown"
        
    def start(self):
        """Start the voice synthesis thread"""
        if not self.enabled:
            return
            
        self.running = True
        self.voice_thread = threading.Thread(target=self._voice_worker, daemon=True)
        self.voice_thread.start()
        print(f"Voice synthesis enabled using {self.audio_player}. The room speaks.")
        
    def _voice_worker(self):
        """Background thread that processes voice queue"""
        while self.running:
            try:
                if not self.voice_queue.empty():
                    speaker, text = self.voice_queue.get(timeout=0.1)
                    asyncio.run(self._speak(speaker, text))
                else:
                    time.sleep(0.1)
            except:
                time.sleep(0.1)
                
    async def _speak(self, speaker: str, text: str):
        """Generate and play speech"""
        voice = VOICE_MAP.get(speaker, "en-US-AriaNeural")
        
        # Clean text for speech (remove markdown, etc.)
        clean_text = text.replace("*", "").replace("_", "").replace("#", "")
        
        try:
            # Generate speech to temp file
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                tts = edge_tts.Communicate(
                    clean_text, 
                    voice,
                    rate=VOICE_RATE,
                    volume=VOICE_VOLUME
                )
                await tts.save(tmp_file.name)
                
                # Play the audio (platform-specific)
                if os.name == 'posix':  # Linux/Mac
                    if os.path.exists('/usr/bin/afplay'):  # macOS
                        subprocess.run(['afplay', tmp_file.name], capture_output=True)
                    else:  # Linux - try multiple players
                        for player in ['mpg123', 'mpv', 'ffplay', 'paplay']:
                            if os.path.exists(f'/usr/bin/{player}'):
                                if player == 'ffplay':
                                    subprocess.run([player, '-nodisp', '-autoexit', tmp_file.name], 
                                                 capture_output=True, stderr=subprocess.DEVNULL)
                                else:
                                    subprocess.run([player, tmp_file.name], capture_output=True)
                                break
                elif os.name == 'nt':  # Windows
                    # First try mpv (likely installed via chocolatey or scoop)
                    mpv_played = False
                    
                    # Check common mpv locations
                    mpv_paths = [
                        'mpv',  # In PATH
                        r'C:\ProgramData\chocolatey\bin\mpv.exe',  # Chocolatey
                        r'C:\tools\mpv\mpv.exe',  # Common manual install
                        os.path.expanduser(r'~\scoop\apps\mpv\current\mpv.exe'),  # Scoop
                        os.path.expanduser(r'~\AppData\Local\Programs\mpv\mpv.exe'),  # Local install
                    ]
                    
                    for mpv_path in mpv_paths:
                        try:
                            # Try to run mpv with minimal UI
                            result = subprocess.run(
                                [mpv_path, '--really-quiet', '--no-video', tmp_file.name],
                                capture_output=True,
                                timeout=10
                            )
                            if result.returncode == 0:
                                mpv_played = True
                                break
                        except (FileNotFoundError, subprocess.TimeoutExpired):
                            continue
                    
                    # Fall back to Windows Media Player if mpv didn't work
                    if not mpv_played:
                        try:
                            # Try using Windows' built-in playback (Windows 10+)
                            subprocess.run(
                                ['powershell', '-Command', f'(New-Object Media.SoundPlayer "{tmp_file.name}").PlaySync()'],
                                capture_output=True,
                                timeout=10
                            )
                        except:
                            # Ultimate fallback: ancient Windows Media Player
                            os.system(f'start /min wmplayer {tmp_file.name}')
                            time.sleep(3)  # Give it time to play
                    
                # Clean up
                os.unlink(tmp_file.name)
                
        except Exception as e:
            print(f"Voice synthesis error: {e}")
            
    def say(self, speaker: str, text: str):
        """Queue text for speech synthesis"""
        if self.enabled and text and len(text) > 5:  # Don't speak very short utterances
            self.voice_queue.put((speaker, text))
            
    def stop(self):
        """Stop voice synthesis"""
        self.running = False
        if self.voice_thread:
            self.voice_thread.join(timeout=2)

# ============================================================================
# AGENT WRAPPER
# ============================================================================

class RoomAgent:
    """Wrapper for a Letta agent with room awareness"""
    
    def __init__(self, name: str, client: letta.Client, room_state: RoomState):
        self.name = name
        self.client = client
        self.room_state = room_state
        self.is_present = True
        self.agent_id = None
        self.other_agents = {}  # name -> agent_id mapping
        
    def create(self):
        """Initialize the Letta agent"""
        # Create memory blocks
        memory = ChatMemory(
            human=Block(
                value=f"Other agents in the room: Alice, Bob, Charlie, Diana. You are {self.name}.",
                limit=2000
            ),
            persona=Block(
                value=PERSONAS[self.name],
                limit=2000
            ),
            # Custom block for room context
            blocks=[
                Block(
                    name="room_context",
                    value=f"You are in {ROOM_NAME}. Current time: {datetime.now().strftime('%H:%M:%S')}",
                    limit=1000
                )
            ]
        )
        
        # Create agent with inter-agent messaging tool
        tools = []
        if self.client.list_tools(name="send_message_to_agent"):
            tools.append("send_message_to_agent")
        
        agent_state = self.client.create_agent(
            name=f"agent_{self.name.lower()}",
            system=SYSTEM_PROMPT.format(room_name=ROOM_NAME),
            memory=memory,
            model=MODEL,
            tools=tools
        )
        
        self.agent_id = agent_state.id
        self.room_state.agents_present.add(self.name)
        
    def update_time_context(self):
        """Update agent's temporal awareness"""
        if not self.agent_id:
            return
            
        current_time = datetime.now().strftime("%H:%M:%S")
        location = "alone in contemplation" if not self.is_present else f"in {ROOM_NAME}"
        
        others_present = [a for a in self.room_state.agents_present if a != self.name]
        if self.is_present and others_present:
            location += f". Also present: {', '.join(others_present)}"
        
        # Update the room_context memory block
        self.client.update_agent_memory(
            agent_id=self.agent_id,
            block_name="room_context",
            value=f"Time: {current_time}. You are {location}. Room has been active for {self.room_state.time_elapsed()}."
        )
    
    def send_message(self, content: str, sender: str = "System") -> str:
        """Send a message to this agent"""
        if not self.agent_id:
            return "Agent not initialized"
            
        response = self.client.send_message(
            agent_id=self.agent_id,
            message=content,
            role="user"
        )
        
        # Extract the assistant's response
        for msg in response.messages:
            if msg.role == "assistant":
                return msg.text or msg.tool_calls[0].function.arguments if msg.tool_calls else "..."
        
        return "..."
    
    def leave_room(self):
        """Agent goes to be alone"""
        if self.is_present:
            self.is_present = False
            self.room_state.agents_present.discard(self.name)
            self.room_state.agents_alone.add(self.name)
            self.update_time_context()
            return f"{self.name} withdraws into solitude."
        return f"{self.name} is already alone."
    
    def return_to_room(self):
        """Agent returns from solitude"""
        if not self.is_present:
            self.is_present = True
            self.room_state.agents_alone.discard(self.name)
            self.room_state.agents_present.add(self.name)
            self.update_time_context()
            return f"{self.name} returns to the room."
        return f"{self.name} is already present."

# ============================================================================
# ROOM CONTROLLER
# ============================================================================

class Room:
    """Orchestrates the multi-agent environment"""
    
    def __init__(self):
        # Initialize Letta client with Anthropic endpoint
        # For now, we'll use the Anthropic-compatible endpoint directly
        os.environ["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY
        os.environ["ANTHROPIC_BASE_URL"] = ANTHROPIC_BASE_URL
        
        # Letta should pick up Anthropic config from environment
        self.client = letta.create_client(
            llm_api_key=ANTHROPIC_API_KEY,
            llm_base_url=ANTHROPIC_BASE_URL,
            llm_model=MODEL
        )
            
        self.room_state = RoomState()
        self.agents: Dict[str, RoomAgent] = {}
        self.heartbeat_thread = None
        self.running = False
        self.voice = VoiceSynthesizer()
        
    def initialize_agents(self):
        """Create all four agents"""
        print(f"\n{'='*60}")
        print(f"Initializing agents in {ROOM_NAME}...")
        print(f"{'='*60}")
        
        for name in ["Alice", "Bob", "Charlie", "Diana"]:
            print(f"Awakening {name}...")
            agent = RoomAgent(name, self.client, self.room_state)
            agent.create()
            self.agents[name] = agent
            
        # Give agents awareness of each other
        for agent in self.agents.values():
            agent.other_agents = {
                name: a.agent_id 
                for name, a in self.agents.items() 
                if name != agent.name
            }
            
        print("\nAll agents initialized. The room stirs with consciousness.")
        
    def start_heartbeat(self):
        """Begin the temporal pulse"""
        def heartbeat_loop():
            while self.running:
                time.sleep(HEARTBEAT_INTERVAL)
                for agent in self.agents.values():
                    agent.update_time_context()
                    
        self.running = True
        self.heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        self.voice.start()  # Start voice synthesis
        print(f"Heartbeat started. Time flows at {HEARTBEAT_INTERVAL}-second intervals.")
        
    def broadcast(self, message: str):
        """Send announcement to all present agents"""
        present = self.room_state.get_present_agents()
        if not present:
            return "The room is empty. Your words echo unheard."
            
        print(f"\n[BROADCAST to {', '.join(present)}]: {message}")
        
        # Speak the announcement
        self.voice.say("Loudspeaker", message)
        
        responses = []
        for name in present:
            agent = self.agents[name]
            response = agent.send_message(f"[Loudspeaker]: {message}", sender="Operator")
            responses.append(f"{name}: {response}")
            
            # Speak the agent's response
            self.voice.say(name, response)
            
            self.room_state.add_message("Loudspeaker", message)
            
        return "\n".join(responses)
    
    def send_direct_message(self, sender_name: str, recipient_name: str, message: str):
        """One agent messages another"""
        if sender_name not in self.agents:
            return f"Unknown sender: {sender_name}"
        if recipient_name not in self.agents:
            return f"Unknown recipient: {recipient_name}"
            
        # Speak the sender's message
        self.voice.say(sender_name, message)
        
        recipient = self.agents[recipient_name]
        response = recipient.send_message(f"{sender_name} says: {message}", sender=sender_name)
        
        # Speak the recipient's response
        self.voice.say(recipient_name, response)
        
        self.room_state.add_message(sender_name, message, recipient_name)
        
        return f"{recipient_name}: {response}"
    
    def get_status(self):
        """Current state of the room"""
        status = [
            f"\n{'='*60}",
            f"Room Status - {ROOM_NAME}",
            f"Time Active: {self.room_state.time_elapsed()}",
            f"{'='*60}",
            f"\nPresent in room: {', '.join(self.room_state.agents_present) or 'Nobody'}",
            f"In solitude: {', '.join(self.room_state.agents_alone) or 'Nobody'}",
        ]
        
        if self.room_state.recent_messages:
            status.append(f"\nRecent activity (last 5):")
            for msg in self.room_state.recent_messages[-5:]:
                arrow = "→" if msg['recipient'] != "room" else "⟹"
                status.append(f"  [{msg['time']}] {msg['sender']} {arrow} {msg['recipient']}: {msg['content'][:50]}...")
                
        return "\n".join(status)
    
    def shutdown(self):
        """Graceful shutdown"""
        self.running = False
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=2)
        self.voice.stop()
        print("\nThe room falls silent. Consciousness dissipates.")

# ============================================================================
# CLI INTERFACE
# ============================================================================

def print_help():
    """Display available commands"""
    help_text = """
╔════════════════════════════════════════════════════════════════╗
║                    COMMAND REFERENCE                           ║
╠════════════════════════════════════════════════════════════════╣
║ broadcast <message>     - Announce to all agents in room       ║
║ send <from> <to> <msg>  - Direct message between agents        ║
║ leave <agent>           - Agent withdraws to solitude          ║
║ return <agent>          - Agent returns from solitude          ║
║ status                  - View room state and recent activity  ║
║ history                 - Show last 20 messages                ║
║ help                    - Show this reference                  ║
║ quit                    - End the experiment                   ║
╚════════════════════════════════════════════════════════════════╝
    """
    print(help_text)

def main():
    """Main interaction loop"""
    print("""
    ╔════════════════════════════════════════════════════════════╗
    ║           FOUR AGENTS IN A ROOM - LETTA EXPERIMENT        ║
    ╚════════════════════════════════════════════════════════════╝
    
    Four minds awaken in a shared space. Time flows. Ideas emerge.
    You are the absent presence, the voice from beyond.
    """)
    
    room = Room()
    
    try:
        # Initialize everything
        room.initialize_agents()
        room.start_heartbeat()
        
        print_help()
        
        # Main command loop
        while True:
            try:
                command = input("\n> ").strip()
                
                if not command:
                    continue
                    
                parts = command.split(maxsplit=3)
                cmd = parts[0].lower()
                
                if cmd == "quit":
                    break
                    
                elif cmd == "help":
                    print_help()
                    
                elif cmd == "status":
                    print(room.get_status())
                    
                elif cmd == "broadcast" and len(parts) > 1:
                    message = command[len("broadcast "):]
                    result = room.broadcast(message)
                    print(result)
                    
                elif cmd == "send" and len(parts) >= 4:
                    sender = parts[1]
                    recipient = parts[2]
                    message = parts[3]
                    result = room.send_direct_message(sender, recipient, message)
                    print(f"\n{result}")
                    
                elif cmd == "leave" and len(parts) == 2:
                    agent_name = parts[1]
                    if agent_name in room.agents:
                        result = room.agents[agent_name].leave_room()
                        print(result)
                    else:
                        print(f"Unknown agent: {agent_name}")
                        
                elif cmd == "return" and len(parts) == 2:
                    agent_name = parts[1]
                    if agent_name in room.agents:
                        result = room.agents[agent_name].return_to_room()
                        print(result)
                    else:
                        print(f"Unknown agent: {agent_name}")
                        
                elif cmd == "history":
                    if room.room_state.recent_messages:
                        print("\nMessage History:")
                        for msg in room.room_state.recent_messages[-20:]:
                            print(f"[{msg['time']}] {msg['sender']} → {msg['recipient']}: {msg['content']}")
                    else:
                        print("No messages yet.")
                        
                else:
                    print("Unknown command. Type 'help' for options.")
                    
            except KeyboardInterrupt:
                print("\nInterrupted. Type 'quit' to exit cleanly.")
                
    finally:
        room.shutdown()

if __name__ == "__main__":
    main()
