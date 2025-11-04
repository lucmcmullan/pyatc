import matplotlib.pyplot as plt
import numpy as np
import math

t = np.linspace(0, 1, 200)

# --- 1. Default smoothstep ---
smoothstep = 3 * t**2 - 2 * t**3

# --- 2. Tunable S-curve (adjustable exponent) ---
def adjustable_curve(t, k):
    t_adj = t ** (1 / k)
    return 3 * t_adj**2 - 2 * t_adj**3

flat_08 = adjustable_curve(t, 0.8)
flat_06 = adjustable_curve(t, 0.6)

# --- 3. Cosine in/out ---
cosine_ease = (1 - np.cos(np.pi * (t ** 1.3))) / 2

# --- 4. Logistic easing (realistic FMS-like) ---
logistic = 1 / (1 + np.exp(-10 * (t - 0.5)))
# normalise logistic (to 0–1 range)
logistic = (logistic - logistic.min()) / (logistic.max() - logistic.min())

# --- Plot ---
plt.figure(figsize=(10, 6))
plt.plot(t, smoothstep, label="Smoothstep (3t² - 2t³)", linewidth=2)
plt.plot(t, flat_08, label="Adjusted (k=0.8)", linewidth=2)
plt.plot(t, flat_06, label="Adjusted (k=0.6)", linewidth=2)
plt.plot(t, cosine_ease, label="Cosine Ease (t¹·³)", linestyle="--")
plt.plot(t, logistic, label="Logistic (realistic autopilot)", linestyle=":")

plt.title("Altitude Easing Profiles — PyATC")
plt.xlabel("Normalized Time (t)")
plt.ylabel("Normalized Altitude Fraction")
plt.grid(True, alpha=0.3)
plt.legend()
plt.tight_layout()
plt.show()