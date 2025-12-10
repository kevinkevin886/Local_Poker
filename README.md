Here is the English translation of your README content:

# Local LAN Texas Hold'em Poker

## ✨ Features

### Core Game Mechanics

  * **Complete Texas Hold'em Rules**: Supports the full flow including Pre-flop, Flop, Turn, River, and Showdown.
  * **Professional Side Pot Logic**: Perfectly handles multi-way All-in scenarios with varying stack sizes to ensure fair pot distribution.
  * **Smart Dealer System**: The Dealer button automatically passes clockwise, intelligently skipping disconnected players or empty seats.
  * **Error-Proofing Mechanism**: The frontend UI automatically calculates the minimum raise amount to prevent incorrect input values.

### User Experience (UX)

  * **Teams-Style Interface**: Adopts Dark Mode and flat design, suitable for office environments or developer gatherings.
  * **Responsive Web Design (RWD)**: Supports desktop, tablet, and mobile browsers. The poker table and seats automatically adapt to the window size.
  * **Real-time Chat Room**:
      * Supports text chat and system message broadcasting.
      * **Emojis**: Built-in emoji picker.
      * **Message Reactions**: Users can like or react to others' messages.
  * **Custom Avatars**: Players can upload images as avatars (with automatic compression) or use default text-based avatars.

## 🚀 Quick Start

### 1\. Install Dependencies

Ensure your computer has Python 3.x installed.

```bash
pip install -r requirements.txt
```

### 2\. Start the Server

```bash
python3 app.py
```

### 3\. Join the Game

```
http://{host.ip}:5000/
```