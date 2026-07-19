const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const scoreElement = document.getElementById('score');
const gameOverDiv = document.getElementById('gameOver');
const finalScoreSpan = document.getElementById('finalScore');
const restartBtn = document.getElementById('restartBtn');

// Game constants
const GROUND_Y = 250;
const DINO_WIDTH = 40;
const DINO_HEIGHT = 50;
const CACTUS_WIDTH = 20;
const CACTUS_HEIGHT = 40;
const GRAVITY = 0.6;
const JUMP_FORCE = -12;
const INITIAL_SPEED = 6;
const SPEED_INCREMENT = 0.001;

// Game state
let gameRunning = true;
let score = 0;
let speed = INITIAL_SPEED;
let frameCount = 0;

// Dino
const dino = {
    x: 50,
    y: GROUND_Y - DINO_HEIGHT,
    width: DINO_WIDTH,
    height: DINO_HEIGHT,
    vy: 0,
    jumping: false,
    ducking: false
};

// Obstacles
let obstacles = [];
let spawnTimer = 0;
const MIN_SPAWN_TIME = 60;
const MAX_SPAWN_TIME = 150;

// Clouds (decorative)
let clouds = [
    { x: 100, y: 40, width: 60, height: 20, speed: 0.5 },
    { x: 400, y: 30, width: 80, height: 20, speed: 0.3 },
    { x: 650, y: 50, width: 50, height: 20, speed: 0.4 }
];

// Input handling
let jumpPressed = false;
let duckPressed = false;

document.addEventListener('keydown', (e) => {
    if (e.code === 'Space' || e.code === 'ArrowUp') {
        e.preventDefault();
        if (!gameRunning) return;
        if (!dino.jumping) {
            dino.vy = JUMP_FORCE;
            dino.jumping = true;
            jumpPressed = true;
        }
    }
    if (e.code === 'ArrowDown') {
        e.preventDefault();
        duckPressed = true;
        if (!gameRunning) return;
        if (!dino.jumping) {
            dino.ducking = true;
            dino.width = 50;
            dino.height = 30;
            dino.y = GROUND_Y - dino.height;
        }
    }
});

document.addEventListener('keyup', (e) => {
    if (e.code === 'Space' || e.code === 'ArrowUp') {
        jumpPressed = false;
    }
    if (e.code === 'ArrowDown') {
        duckPressed = false;
        if (dino.ducking) {
            dino.ducking = false;
            dino.width = DINO_WIDTH;
            dino.height = DINO_HEIGHT;
            dino.y = GROUND_Y - dino.height;
        }
    }
});

function restartGame() {
    gameRunning = true;
    score = 0;
    speed = INITIAL_SPEED;
    frameCount = 0;
    obstacles = [];
    spawnTimer = 0;
    dino.y = GROUND_Y - DINO_HEIGHT;
    dino.vy = 0;
    dino.jumping = false;
    dino.ducking = false;
    dino.width = DINO_WIDTH;
    dino.height = DINO_HEIGHT;
    gameOverDiv.style.display = 'none';
    scoreElement.textContent = 'Score: 0';
}

restartBtn.addEventListener('click', restartGame);

function update() {
    if (!gameRunning) return;

    frameCount++;
    score++;
    speed += SPEED_INCREMENT;

    // Dino physics
    if (dino.jumping) {
        dino.vy += GRAVITY;
        dino.y += dino.vy;
        if (dino.y >= GROUND_Y - dino.height) {
            dino.y = GROUND_Y - dino.height;
            dino.vy = 0;
            dino.jumping = false;
        }
    }

    // Spawn obstacles
    spawnTimer--;
    if (spawnTimer <= 0) {
        obstacles.push({
            x: canvas.width,
            y: GROUND_Y - CACTUS_HEIGHT,
            width: CACTUS_WIDTH,
            height: CACTUS_HEIGHT,
            passed: false
        });
        spawnTimer = Math.floor(Math.random() * (MAX_SPAWN_TIME - MIN_SPAWN_TIME)) + MIN_SPAWN_TIME;
        // Randomize spawn timer based on speed
        spawnTimer = Math.max(30, spawnTimer - speed * 2);
    }

    // Move obstacles
    for (let i = obstacles.length - 1; i >= 0; i--) {
        obstacles[i].x -= speed;
        if (obstacles[i].x + obstacles[i].width < 0) {
            obstacles.splice(i, 1);
        }
    }

    // Collision detection
    for (let obs of obstacles) {
        if (checkCollision(dino, obs)) {
            gameOver();
            break;
        }
    }

    // Move clouds
    for (let cloud of clouds) {
        cloud.x -= cloud.speed;
        if (cloud.x + cloud.width < 0) {
            cloud.x = canvas.width + Math.random() * 200;
            cloud.y = Math.random() * 80 + 10;
        }
    }

    // Update score display
    scoreElement.textContent = 'Score: ' + Math.floor(score / 10);
}

function checkCollision(dino, obs) {
    // Simple rectangular collision with some margin
    const margin = 5;
    const dinoRect = {
        x: dino.x + margin,
        y: dino.y + margin,
        width: dino.width - margin * 2,
        height: dino.height - margin * 2
    };
    const obsRect = {
        x: obs.x,
        y: obs.y,
        width: obs.width,
        height: obs.height
    };
    return dinoRect.x < obsRect.x + obsRect.width &&
           dinoRect.x + dinoRect.width > obsRect.x &&
           dinoRect.y < obsRect.y + obsRect.height &&
           dinoRect.y + dinoRect.height > obsRect.y;
}

function gameOver() {
    gameRunning = false;
    finalScoreSpan.textContent = Math.floor(score / 10);
    gameOverDiv.style.display = 'block';
}

function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Sky gradient
    const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
    gradient.addColorStop(0, '#87CEEB');
    gradient.addColorStop(1, '#E0F7FA');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Ground
    ctx.fillStyle = '#8B4513';
    ctx.fillRect(0, GROUND_Y, canvas.width, canvas.height - GROUND_Y);
    ctx.fillStyle = '#654321';
    ctx.fillRect(0, GROUND_Y-3, canvas.width, 3);

    // Clouds
    ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
    for (let cloud of clouds) {
        ctx.beginPath();
        ctx.ellipse(cloud.x, cloud.y, cloud.width/2, cloud.height/2, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.ellipse(cloud.x + 20, cloud.y - 5, cloud.width/3, cloud.height/2, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.ellipse(cloud.x - 15, cloud.y + 5, cloud.width/4, cloud.height/3, 0, 0, Math.PI * 2);
        ctx.fill();
    }

    // Obstacles (cacti)
    ctx.fillStyle = '#228B22';
    for (let obs of obstacles) {
        ctx.fillRect(obs.x, obs.y, obs.width, obs.height);
        // Simple spikes
        ctx.beginPath();
        ctx.moveTo(obs.x - 5, obs.y + 5);
        ctx.lineTo(obs.x, obs.y - 5);
        ctx.lineTo(obs.x + 5, obs.y + 5);
        ctx.fill();
        ctx.beginPath();
        ctx.moveTo(obs.x + obs.width - 5, obs.y + 5);
        ctx.lineTo(obs.x + obs.width, obs.y - 5);
        ctx.lineTo(obs.x + obs.width + 5, obs.y + 5);
        ctx.fill();
    }

    // Dino
    if (dino.ducking) {
        // Ducking dino - flat
        ctx.fillStyle = '#4a4a4a';
        ctx.fillRect(dino.x, dino.y, dino.width, dino.height);
        // Eyes
        ctx.fillStyle = 'white';
        ctx.fillRect(dino.x + 30, dino.y + 8, 8, 8);
        ctx.fillStyle = 'black';
        ctx.fillRect(dino.x + 34, dino.y + 10, 4, 4);
        // Mouth
        ctx.fillStyle = 'red';
        ctx.fillRect(dino.x + 35, dino.y + 18, 6, 3);
    } else {
        // Normal dino - tall (simple T-Rex shape)
        ctx.fillStyle = '#4a4a4a';
        // Body
        ctx.fillRect(dino.x, dino.y + 10, dino.width, dino.height - 10);
        // Head
        ctx.fillRect(dino.x + 5, dino.y - 5, dino.width - 5, 20);
        // Eye
        ctx.fillStyle = 'white';
        ctx.fillRect(dino.x + 25, dino.y - 2, 8, 8);
        ctx.fillStyle = 'black';
        ctx.fillRect(dino.x + 28, dino.y, 4, 4);
        // Mouth
        ctx.fillStyle = '#cc0000';
        ctx.fillRect(dino.x + 30, dino.y + 8, 6, 3);
        // Legs (animated)
        ctx.fillStyle = '#3a3a3a';
        const legOffset = Math.sin(frameCount * 0.3) * 5;
        ctx.fillRect(dino.x + 5, dino.y + dino.height - 5, 8, 10 + legOffset);
        ctx.fillRect(dino.x + 20, dino.y + dino.height - 5, 8, 10 - legOffset);
        // Tail
        ctx.fillRect(dino.x - 10, dino.y + 25, 10, 5);
    }
}

function gameLoop() {
    update();
    draw();
    requestAnimationFrame(gameLoop);
}

gameLoop();
