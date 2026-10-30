"""Matplotlib plots of an optimized portfolio and of the per-asset simulated distributions."""
# ==============================================================================
# PROJECT: Roptimizer
# AUTHOR: Eljon Rrodhe (eljonrrodhe11@gmail.com)
# COPYRIGHT: © 2026 Eljon Rrodhe
# LICENSE: Apache License 2.0 (see the LICENSE file)
# ==============================================================================


import numpy as np
from scipy.stats import norm, kurtosis
import matplotlib.pyplot as plt


def plot_optimized_port(prices,weights,paths):
    # --- Step 4: Visualize the portfolio results as a line plot and a histogram ---
    import matplotlib.pyplot as plt
    plt.style.use('dark_background')
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

    # --- Line Plot of Simulated Paths ---
    # Calculate the initial portfolio value
    initial_portfolio_value = np.dot(prices, weights)

    # Randomly select a sample of paths to plot for performance
    sample_size = min(50000, paths.shape[0])
    random_indices = np.random.choice(paths.shape[0], size=sample_size, replace=False)
    sampled_paths = paths[random_indices, :]

    # Convert sampled dollar values to percentage returns
    simulated_returns_paths = ((sampled_paths - initial_portfolio_value) / initial_portfolio_value) * 100
    ax1.plot(simulated_returns_paths.T, color='cyan', alpha=0.1)

    # Plot the average portfolio path
    average_returns_path = np.mean(((paths - initial_portfolio_value) / initial_portfolio_value) * 100, axis=0)
    ax1.plot(average_returns_path, color='red', linewidth=2, label='Average Portfolio Return')
    ax1.axhline(0, color='white', linestyle='--', linewidth=1, label='Zero Return Line')

    # Add a dashed red line to show the final average return
    final_avg_return = average_returns_path[-1]
    ax1.axhline(final_avg_return, color='red', linestyle='--', linewidth=1, label=f'Final Avg. Return: {final_avg_return:.2f}%')

    # Add annotation for the final percentage return on the left axis
    ax1.annotate(
        f'{final_avg_return:.2f}%',
        xy=(0, final_avg_return),
        xytext=(-10, 0),  # Offset slightly to the left
        textcoords='offset points',
        ha='right',
        va='center',
        color='red',
        fontsize=10,
        fontweight='bold'
    )

    ax1.set_title('Monte Carlo Simulation of Portfolio Returns', color='white')
    ax1.set_xlabel('Time Steps', color='white')
    ax1.set_ylabel('Portfolio Return (%)', color='white')
    ax1.legend(frameon=False, loc='upper left')
    ax1.grid(True, linestyle='--', alpha=0.2)

    # --- Histogram of Final Returns ---
    # Get the final portfolio values from all simulations
    final_values = paths[:, -1]

    # Calculate the returns from the initial value to the final value
    final_returns = (final_values - initial_portfolio_value) / initial_portfolio_value

    # Plot the histogram of final returns
    ax2.hist(final_returns, bins=100, color='lime', edgecolor='white', alpha=0.7, density=True)

    # Calculate and plot the normal distribution curve
    mu, sigma = np.mean(final_returns), np.std(final_returns)
    x_vals = np.linspace(min(final_returns), max(final_returns), 100)
    pdf_vals = norm.pdf(x_vals, mu, sigma)
    ax2.plot(x_vals, pdf_vals, color='red', linestyle='-', linewidth=2, label='Normal Distribution')

    ax2.set_title('Distribution of Final Portfolio Returns', color='white')
    ax2.set_xlabel('Final Return (%)', color='white')
    ax2.set_ylabel('Frequency', color='white')
    ax2.grid(True, linestyle='--', alpha=0.2)
    ax2.get_xaxis().set_major_formatter(plt.FuncFormatter(lambda x, loc: f'{x*100:.0f}%'))
    ax2.legend(frameon=False)

    plt.tight_layout()
    plt.show()


def plot_all_asset_distributions(raw_asset_returns, tickers,log_state=True):
    """
    Plots the final return distribution for EVERY single asset in the portfolio.
    It overlays a Normal Distribution curve to visually prove that individual
    assets have Fat Tails (high Kurtosis), contrasting with the Portfolio's normality.
    """
    num_assets = len(tickers)

    # Calculate grid dimensions (e.g., 4 columns wide)
    cols = 4
    rows = (num_assets // cols) + (1 if num_assets % cols > 0 else 0)

    # Create the figure
    fig, axes = plt.subplots(rows, cols, figsize=(20, 4 * rows))
    plt.style.use('dark_background')
    axes = axes.flatten()

    for i, ticker in enumerate(tickers):
        ax = axes[i]

        # Extract the specific row for this asset and convert to Percentage
        data = raw_asset_returns[i, :] * 100

        # Calculate Statistics
        mu, std = np.mean(data), np.std(data)
        ku = kurtosis(data) # Normal Distribution has Excess Kurtosis = 0

        # 1. Plot Histogram (The Reality)
        # We limit the range to +/- 4 std devs to keep the plot readable,
        # but the data extends further (the fat tail).
        ax.hist(data, bins=80, range=(mu-4*std, mu+4*std), density=True,
                color='#1f77b4', alpha=0.7, label='Simulated',log=log_state)

        # 2. Plot Normal Distribution Overlay (The Control)
        x = np.linspace(mu-4*std, mu+4*std, 100)
        p = norm.pdf(x, mu, std)
        ax.plot(x, p, 'r--', linewidth=2, label='Normal Dist')

        # 3. Formatting & Annotations
        ax.set_title(f"{ticker}\nKurtosis: {ku:.2f}", fontsize=10, fontweight='bold', color='white')
        ax.axvline(0, color='gray', linestyle=':', alpha=0.5)

        # Visual Flag: If Kurtosis is high, mark it as a Fat Tail
        if ku > 1.0:
            ax.text(0.05, 0.90, "FAT TAIL", transform=ax.transAxes, color='yellow', fontsize=8, fontweight='bold')

    # Turn off any unused empty subplots
    for j in range(num_assets, len(axes)):
        axes[j].axis('off')

    plt.tight_layout()
    plt.show()
