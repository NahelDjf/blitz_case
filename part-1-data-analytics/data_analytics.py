import pandas as pd
from pathlib import Path


# Load CSV
CSV = Path(__file__).parent / "transactions.csv"
df = pd.read_csv(CSV, sep=";")


# 1. Overall Success Rate
print("1. Overall Success Rate")
total_transactions = len(df)
successful_transactions = (df['Success?'] == 'Yes').sum()
success_rate = successful_transactions / total_transactions * 100
print(f"Total Transactions: {total_transactions}")
print(f"Overall Success Rate: {success_rate:.2f}%\n")


# 2. Breakdown by Payment Method 
print("2. Breakdown by Payment Method (%)")
method_breakdown = df.groupby('Method')['Success?'].value_counts(normalize=True).unstack() * 100
print(method_breakdown.round(2), "\n")


# 3. Amount vs. Success
print("3. Amount vs. Success (first look)")
avg_amounts = df.groupby('Success?')['Amount'].mean()
print("Average Transaction Amount:")
print(avg_amounts.round(2))

df['Amount Category'] = pd.cut(df['Amount'], bins=[0, 25, 50, 100],
                               labels=['Low (0-25)', 'Medium (25-50)', 'High (50-100)'])
amount_breakdown = (df.groupby('Amount Category', observed=True)['Success?']
                    .value_counts(normalize=True).unstack() * 100)
print("\nSuccess/Failure Rate by Amount Category:")
print(amount_breakdown.round(2), "\n")


# 4. Finding an Amount Threshold
print("4. Finding an Amount Threshold")

# (a) Failure rate per 10-unit bin
df['Bin10'] = pd.cut(df['Amount'], bins=range(0, 111, 10), right=False)
bin_stats = df.groupby('Bin10', observed=True).agg(
    n=('Amount', 'size'),
    failures=('Success?', lambda s: (s == 'No').sum()),
)
bin_stats['fail_rate_%'] = (bin_stats['failures'] / bin_stats['n'] * 100).round(1)
print("(a) Failure rate per 10-unit bin:")
print(bin_stats, "\n")

# (b) Threshold sweep
rows = []
for t in range(10, 101, 10):
    below = df[df['Amount'] < t]
    above = df[df['Amount'] >= t]
    rows.append({
        'T': t,
        'n < T': len(below),
        'fail% < T': round((below['Success?'] == 'No').mean() * 100, 1),
        'n >= T': len(above),
        'fail% >= T': round((above['Success?'] == 'No').mean() * 100, 1),
        'jump (pp)': round(((above['Success?'] == 'No').mean()
                            - (below['Success?'] == 'No').mean()) * 100, 1),
    })
sweep = pd.DataFrame(rows).set_index('T')
print("(b) Threshold sweep (fail rate below T vs >= T):")
print(sweep, "\n")

# (c) Chosen threshold
THRESHOLD = 40
below = df[df['Amount'] < THRESHOLD]
above = df[df['Amount'] >= THRESHOLD]
print(f"(c) Threshold: Amount = {THRESHOLD}")
print(f"    Below {THRESHOLD}: {len(below)} txns, "
      f"{(below['Success?']=='No').mean()*100:.2f}% failure rate")
print(f"    >= {THRESHOLD}:    {len(above)} txns, "
      f"{(above['Success?']=='No').mean()*100:.2f}% failure rate\n")


# 5. Amount vs. Method
print("5. Amount vs. Method")

# (a) Amount range per method
print("(a) Amount range per payment method:")
print(df.groupby('Method')['Amount'].agg(['min', 'max', 'mean', 'count']).round(1), "\n")

# (b) Cross-tab: Amount bucket x Method
df['Bucket20'] = pd.cut(df['Amount'], bins=[0, 20, 40, 60, 80, 101], right=False,
                        labels=['[0,20)', '[20,40)', '[40,60)', '[60,80)', '[80,100]'])
counts = (df.groupby(['Bucket20', 'Method'], observed=True).size()
          .unstack('Method').fillna(0).astype(int))
fail_rate = (df.groupby(['Bucket20', 'Method'], observed=True)['Success?']
             .apply(lambda s: (s == 'No').mean() * 100)
             .unstack('Method').round(1))
print("(b) Transaction counts by Amount bucket x Method:")
print(counts, "\n")
print("(b) Failure rate (%) by Amount bucket x Method:")
print(fail_rate)