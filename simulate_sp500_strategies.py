import pandas as pd
import numpy as np
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def simulate_options_strategies(filepath):
    try:
        df = pd.read_csv(filepath)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return
        
    df = df.dropna(subset=['Change (%)']).copy()
    
    # Filter for tickers with at least 8 earnings reports
    ticker_counts = df['Ticker'].value_counts()
    valid_tickers = ticker_counts[ticker_counts >= 8].index.tolist()
    df_filtered = df[df['Ticker'].isin(valid_tickers)].copy()
    
    # Define strategy win conditions
    df_filtered['BPS_Win_5'] = df_filtered['Change (%)'] > -5.0
    df_filtered['BCS_Win_5'] = df_filtered['Change (%)'] < 5.0
    df_filtered['IC_Win_5'] = (df_filtered['Change (%)'] >= -5.0) & (df_filtered['Change (%)'] <= 5.0)
    df_filtered['IC_Win_3'] = (df_filtered['Change (%)'] >= -3.0) & (df_filtered['Change (%)'] <= 3.0)
    df_filtered['IC_Win_7'] = (df_filtered['Change (%)'] >= -7.0) & (df_filtered['Change (%)'] <= 7.0)
    
    # Group by ticker and calculate win rates
    sim_results = df_filtered.groupby('Ticker').agg(
        total_reports=('Change (%)', 'count'),
        bps_win_rate_5=('BPS_Win_5', 'mean'),
        bcs_win_rate_5=('BCS_Win_5', 'mean'),
        ic_win_rate_5=('IC_Win_5', 'mean'),
        ic_win_rate_3=('IC_Win_3', 'mean'),
        ic_win_rate_7=('IC_Win_7', 'mean'),
        avg_abs_move=('Change (%)', lambda x: x.abs().mean())
    )
    
    # Convert to percentages
    for col in ['bps_win_rate_5', 'bcs_win_rate_5', 'ic_win_rate_5', 'ic_win_rate_3', 'ic_win_rate_7']:
        sim_results[col] = sim_results[col] * 100
        
    sim_results = sim_results.round(2)
    sim_results = sim_results.reset_index()
    
    # Save results
    output_file = os.path.join(SCRIPT_DIR, "sp500_strategy_simulations.csv")
    sim_results.to_csv(output_file, index=False)
    print(f"Saved simulation results to {output_file}!")
    
    # Print findings
    print("\n=== TOP 5 RECOMMENDED S&P 500 BULL PUT SPREADS (Short Strike at -5%) ===")
    top_bps = sim_results.sort_values(by='bps_win_rate_5', ascending=False).head(5)
    print(top_bps[['Ticker', 'bps_win_rate_5', 'avg_abs_move', 'total_reports']].to_markdown(index=False))
    
    print("\n=== TOP 5 RECOMMENDED S&P 500 BEAR CALL SPREADS (Short Strike at +5%) ===")
    top_bcs = sim_results.sort_values(by='bcs_win_rate_5', ascending=False).head(5)
    print(top_bcs[['Ticker', 'bcs_win_rate_5', 'avg_abs_move', 'total_reports']].to_markdown(index=False))
    
    print("\n=== TOP 5 RECOMMENDED S&P 500 IRON CONDORS (Short Strikes at ±5%) ===")
    top_ic5 = sim_results.sort_values(by='ic_win_rate_5', ascending=False).head(5)
    print(top_ic5[['Ticker', 'ic_win_rate_5', 'ic_win_rate_7', 'avg_abs_move', 'total_reports']].to_markdown(index=False))
    
    print("\n=== TOP 5 RECOMMENDED S&P 500 TIGHT IRON CONDORS (Short Strikes at ±3% - High Yield) ===")
    top_ic3 = sim_results.sort_values(by='ic_win_rate_3', ascending=False).head(5)
    print(top_ic3[['Ticker', 'ic_win_rate_3', 'ic_win_rate_5', 'avg_abs_move', 'total_reports']].to_markdown(index=False))

if __name__ == "__main__":
    simulate_options_strategies(os.path.join(SCRIPT_DIR, "sp500_earnings_reactions.csv"))
