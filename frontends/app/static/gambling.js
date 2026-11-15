const BALANCE_KEY = "sumirrorize.play-coins.v1";
const SYMBOLS_KEY = "sumirrorize.slot-images.v1";
const STARTING_COINS = 1000;
const coinBalance = document.querySelector("#coin-balance");
const betInput = document.querySelector("#bet-amount");
const track = document.querySelector("#game-track");
const panels = [...document.querySelectorAll(".game-panel")];
const gameButtons = [...document.querySelectorAll("[data-game-index]")];
const coinArt = document.querySelector("#coin-art");
let balance = readBalance();
let dicePoint = null;
let raceRunning = false;
let rocketTimer = null;
let rocketStart = 0;
let rocketCrashAt = 0;
let rocketStake = 0;

function readBalance() {
  try {
    const stored = Number(localStorage.getItem(BALANCE_KEY));
    return Number.isSafeInteger(stored) && stored >= 0 ? stored : STARTING_COINS;
  } catch {
    return STARTING_COINS;
  }
}

function saveBalance() {
  try { localStorage.setItem(BALANCE_KEY, String(balance)); } catch { }
  coinBalance.value = balance.toLocaleString();
  coinBalance.textContent = balance.toLocaleString();
  betInput.max = String(Math.max(1, balance));
}

function stakeCoins() {
  const stake = Number(betInput.value);
  if (!Number.isSafeInteger(stake) || stake < 1) return fail("Enter a whole-number wager of at least 1 coin.");
  if (stake > balance) return fail("That wager is larger than your balance.");
  balance -= stake;
  saveBalance();
  return stake;
}

function settle(stake, multiplier) {
  const winnings = Math.floor(stake * multiplier);
  balance += winnings;
  saveBalance();
  return winnings;
}

function fail(message) {
  document.querySelector("#casino-message").textContent = message;
  return null;
}

function announce(element, message) {
  element.textContent = message;
  document.querySelector("#casino-message").textContent = "";
}

function currentIndex() {
  return Math.round(track.scrollLeft / track.clientWidth);
}

function goToGame(index) {
  const target = Math.max(0, Math.min(panels.length - 1, index));
  panels[target].scrollIntoView({ behavior: "smooth", block: "nearest", inline: "start" });
  updateGameNav(target);
}

function updateGameNav(index = currentIndex()) {
  gameButtons.forEach((button, buttonIndex) => {
    if (buttonIndex === index) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  });
  document.querySelector("#game-position").textContent = `${String(index + 1).padStart(2, "0")} / 06`;
}

gameButtons.forEach((button) => button.addEventListener("click", () => goToGame(Number(button.dataset.gameIndex))));
document.querySelectorAll("[data-step]").forEach((button) => button.addEventListener("click", () => goToGame(currentIndex() + Number(button.dataset.step))));
track.addEventListener("scroll", () => updateGameNav(), { passive: true });
window.addEventListener("resize", () => goToGame(currentIndex()));

document.querySelectorAll("[data-flip]").forEach((button) => button.addEventListener("click", () => {
  const stake = stakeCoins();
  if (stake === null) return;
  const outcome = Math.random() < 0.5 ? "heads" : "tails";
  coinArt.textContent = outcome === "heads" ? "M" : "FOX";
  coinArt.classList.remove("flip");
  void coinArt.offsetWidth;
  coinArt.classList.add("flip");
  if (button.dataset.flip === outcome) {
    const winnings = settle(stake, 2);
    announce(document.querySelector("#flip-result"), `${outcome.toUpperCase()}! You won ${winnings} coins.`);
  } else announce(document.querySelector("#flip-result"), `${outcome.toUpperCase()}. Your ${stake} coin wager is gone.`);
}));

const slotFaces = ["M", "FOX", "RED", "845", "PAW"];
let slotImages = readSlotImages();
function readSlotImages() {
  try {
    const saved = JSON.parse(localStorage.getItem(SYMBOLS_KEY) || "[]");
    return Array.isArray(saved) ? saved.slice(0, 5) : [];
  } catch { return []; }
}
function renderReel(reel, symbolIndex) {
  const custom = slotImages[symbolIndex];
  reel.replaceChildren();
  if (custom) {
    const image = document.createElement("img");
    image.src = custom;
    image.alt = `Custom slot symbol ${symbolIndex + 1}`;
    reel.append(image);
  } else reel.textContent = slotFaces[symbolIndex];
  reel.dataset.symbol = String(symbolIndex);
}
document.querySelectorAll(".slot-reel").forEach((reel, index) => renderReel(reel, index));

document.querySelector("#spin-slots").addEventListener("click", () => {
  const stake = stakeCoins();
  if (stake === null) return;
  const reels = [...document.querySelectorAll(".slot-reel")];
  const results = reels.map((reel) => {
    const index = Math.floor(Math.random() * slotFaces.length);
    renderReel(reel, index);
    return index;
  });
  const counts = new Map(results.map((value) => [value, results.filter((item) => item === value).length]));
  const matches = Math.max(...counts.values());
  if (matches === 3) {
    const winnings = settle(stake, 4);
    announce(document.querySelector("#slots-result"), `Three of a kind. ${winnings} coins returned.`);
  } else if (matches === 2) {
    const winnings = settle(stake, 1);
    announce(document.querySelector("#slots-result"), `A pair. Your ${winnings} coin wager is returned.`);
  } else announce(document.querySelector("#slots-result"), `No match. Your ${stake} coin wager is gone.`);
});

function resizeImage(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read one of those images."));
    reader.onload = () => {
      const image = new Image();
      image.onerror = () => reject(new Error("One of those files is not a usable image."));
      image.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = 120;
        canvas.height = 120;
        const scale = Math.min(120 / image.width, 120 / image.height);
        const width = image.width * scale;
        const height = image.height * scale;
        canvas.getContext("2d").drawImage(image, (120 - width) / 2, (120 - height) / 2, width, height);
        resolve(canvas.toDataURL("image/jpeg", 0.78));
      };
      image.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}
document.querySelector("#slot-images").addEventListener("change", async (event) => {
  const files = [...event.target.files].slice(0, 5);
  if (!files.length) return;
  try {
    slotImages = await Promise.all(files.map(resizeImage));
    localStorage.setItem(SYMBOLS_KEY, JSON.stringify(slotImages));
    document.querySelectorAll(".slot-reel").forEach((reel) => renderReel(reel, Number(reel.dataset.symbol)));
    announce(document.querySelector("#slots-result"), `${slotImages.length} custom symbol images saved on this browser.`);
  } catch {
    fail("Those images could not be saved here. Try smaller files or clear some browser storage.");
  }
  event.target.value = "";
});

document.querySelector("#start-race").addEventListener("click", () => {
  if (raceRunning) return;
  const stake = stakeCoins();
  if (stake === null) return;
  raceRunning = true;
  const progress = [0, 0, 0, 0];
  const lanes = [...document.querySelectorAll(".race-lane i")];
  lanes.forEach((lane) => { lane.style.width = "0"; });
  const chosen = Number(document.querySelector("#horse-pick").value);
  const odds = [2, 3, 4, 5];
  announce(document.querySelector("#racing-result"), "And they're off!");
  const timer = setInterval(() => {
    progress.forEach((value, index) => {
      progress[index] = value + 1 + Math.random() * 5;
      lanes[index].style.width = `${Math.min(96, progress[index])}%`;
    });
    if (Math.max(...progress) >= 96) {
      clearInterval(timer);
      const winner = progress.indexOf(Math.max(...progress));
      raceRunning = false;
      if (winner === chosen) {
        const winnings = settle(stake, odds[chosen]);
        announce(document.querySelector("#racing-result"), `Your runner wins! ${winnings} coins returned.`);
      } else announce(document.querySelector("#racing-result"), `${["Red Fox", "North Poughkeepsie", "River Runner", "The 845"][winner]} takes it. Wager lost.`);
    }
  }, 110);
});

const pachinkoMultipliers = [0, 0.5, 1, 2, 5, 2, 1, 0.5, 0];
const pachinkoWeights = [4, 9, 15, 17, 4, 17, 15, 9, 4];
function weightedPachinkoBin() {
  let draw = Math.random() * pachinkoWeights.reduce((sum, weight) => sum + weight, 0);
  return pachinkoWeights.findIndex((weight) => (draw -= weight) < 0);
}
document.querySelector("#drop-ball").addEventListener("click", () => {
  const stake = stakeCoins();
  if (stake === null) return;
  const bin = weightedPachinkoBin();
  const multiplier = pachinkoMultipliers[bin];
  const ball = document.querySelector("#pachinko-ball");
  ball.classList.remove("drop");
  void ball.offsetWidth;
  ball.style.left = `${11 + bin * 9.5}%`;
  ball.classList.add("drop");
  const result = document.querySelector("#pachinko-result");
  if (multiplier > 0) {
    const winnings = settle(stake, multiplier);
    announce(result, `${multiplier}× pocket. ${winnings} coins returned.`);
  } else announce(result, `Empty pocket. Your ${stake} coin wager is gone.`);
});

document.querySelector("#launch-rocket").addEventListener("click", () => {
  if (rocketTimer) return;
  const stake = stakeCoins();
  if (stake === null) return;
  rocketStake = stake;
  rocketStart = Date.now();
  rocketCrashAt = Math.max(1.01, Math.min(20, 1 / (1 - Math.random() * 0.93)));
  document.querySelector("#launch-rocket").disabled = true;
  document.querySelector("#cash-out").disabled = false;
  announce(document.querySelector("#rocket-result"), "In flight. Cash out in time.");
  rocketTimer = setInterval(() => {
    const multiplier = Math.exp((Date.now() - rocketStart) / 18000);
    document.querySelector("#rocket-multiplier").textContent = `${multiplier.toFixed(2)}×`;
    document.querySelector("#rocket-icon").style.left = `${Math.min(83, 12 + multiplier * 5)}%`;
    document.querySelector("#rocket-icon").style.bottom = `${Math.min(74, 20 + multiplier * 5)}px`;
    if (multiplier >= rocketCrashAt) finishRocket(false, multiplier);
  }, 40);
});
function finishRocket(cashedOut, multiplier) {
  clearInterval(rocketTimer);
  rocketTimer = null;
  document.querySelector("#launch-rocket").disabled = false;
  document.querySelector("#cash-out").disabled = true;
  if (cashedOut) {
    const winnings = settle(rocketStake, multiplier);
    announce(document.querySelector("#rocket-result"), `Cashed out at ${multiplier.toFixed(2)}×. ${winnings} coins returned.`);
  } else announce(document.querySelector("#rocket-result"), `Rocket burst at ${multiplier.toFixed(2)}×. Wager lost.`);
}
document.querySelector("#cash-out").addEventListener("click", () => {
  if (rocketTimer) {
    const multiplier = Math.exp((Date.now() - rocketStart) / 18000);
    finishRocket(multiplier < rocketCrashAt, multiplier);
  }
});

const dieFaces = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"];
function rollDie() { return Math.floor(Math.random() * 6) + 1; }
function rollCraps() {
  const first = rollDie();
  const second = rollDie();
  document.querySelector("#die-one").textContent = dieFaces[first - 1];
  document.querySelector("#die-two").textContent = dieFaces[second - 1];
  return first + second;
}
document.querySelector("#roll-dice").addEventListener("click", () => {
  const result = document.querySelector("#craps-result");
  if (dicePoint === null) {
    const stake = stakeCoins();
    if (stake === null) return;
    const total = rollCraps();
    if ([7, 11].includes(total)) {
      const winnings = settle(stake, 2);
      announce(result, `${total}, natural! ${winnings} coins returned.`);
    } else if ([2, 3, 12].includes(total)) announce(result, `${total}, craps. Wager lost.`);
    else {
      dicePoint = total;
      document.querySelector("#roll-dice").textContent = `Roll for ${dicePoint}`;
      document.querySelector("#roll-dice").dataset.stake = String(stake);
      announce(result, `Point is ${dicePoint}. Keep rolling.`);
    }
  } else {
    const total = rollCraps();
    if (total === dicePoint) {
      const winnings = settle(Number(document.querySelector("#roll-dice").dataset.stake), 2);
      dicePoint = null;
      document.querySelector("#roll-dice").textContent = "Roll dice";
      announce(result, `${total}, point made! ${winnings} coins returned.`);
    } else if (total === 7) {
      dicePoint = null;
      document.querySelector("#roll-dice").textContent = "Roll dice";
      announce(result, "Seven out. Wager lost.");
    } else announce(result, `${total}. Point is ${dicePoint}; roll again.`);
  }
});

document.querySelector("#reset-coins").addEventListener("click", () => {
  if (!window.confirm("Reset your local play coin balance to 1,000?")) return;
  balance = STARTING_COINS;
  saveBalance();
  document.querySelector("#casino-message").textContent = "Play coin balance reset.";
});

saveBalance();