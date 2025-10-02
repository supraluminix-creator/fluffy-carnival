
import sys
from datetime import datetime

try:
	from tabulate import tabulate  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - dépendance optionnelle
    tabulate = None
import pandas as pd


class Reporter:
	"""Reporting PowerShell-friendly, tabulate or pandas fallback."""
	def __init__(self):
		self.use_tabulate = tabulate is not None

	def display_summary(
		self,
		data: dict,
		fgi_data: dict | None = None,
		additional_data: dict | None = None,
		signals: dict | None = None,
		dune_data: dict | None = None,
		stream=sys.stdout,
	):
		print(f"\n📊 CRYPTO MONITOR - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", file=stream)
		print("=" * 100, file=stream)
		mc = data.get('global', {})
		v_mc_ratio = mc.get('total_volume', {}).get('usd', 0) / mc.get('total_market_cap', {}).get('usd', 1) if mc.get('total_market_cap', {}).get('usd', 0) > 0 else 0
		print(f"🌍 MACRO: Cap ${mc.get('total_market_cap',{}).get('usd',0)/1e12:.2f}T | Vol ${mc.get('total_volume',{}).get('usd',0)/1e9:.1f}B", file=stream)
		print(f"📈 BTC Dominance: {mc.get('market_cap_percentage',{}).get('btc','N/A'):.1f}% | 24h Change: {mc.get('market_cap_change_percentage_24h_usd','N/A'):+.2f}%", file=stream)
		print(f"📊 Ratio Volume/MarketCap: {v_mc_ratio:.4f}", file=stream)

		if additional_data and 'stablecoins' in additional_data:
			sc_data = additional_data['stablecoins']
			print(f"💵 Stablecoins: ${sc_data.get('total_supply',0)/1e9:.1f}B (USDT: {sc_data.get('usdt_dominance','N/A'):.1f}%, USDC: {sc_data.get('usdc_dominance','N/A'):.1f}%)", file=stream)

		# Dune Analytics
		if dune_data:
			print("\n📊 DONNÉES DUNE ANALYTICS:", file=stream)
			for query_name, result in dune_data.items():
				if result is not None and hasattr(result, 'empty') and not result.empty:
					if query_name == 'exchange_flows_ethereum':
						net_flow = result.iloc[0].get('net_flow', 'N/A')
						print(f"   📈 Flux nets Ethereum: {net_flow}", file=stream)
					elif query_name == 'bitcoin_cex_reserves':
						reserves = result.iloc[0].get('reserves', 'N/A')
						print(f"   ₿ Réserves BTC CEX: {reserves}", file=stream)
					elif query_name == 'ethereum_cex_reserves':
						reserves = result.iloc[0].get('reserves', 'N/A')
						print(f"   🔷 Réserves ETH CEX: {reserves}", file=stream)
					elif query_name == 'link_cex_reserves':
						reserves = result.iloc[0].get('reserves', 'N/A')
						print(f"   🔗 Réserves LINK CEX: {reserves}", file=stream)
					elif query_name == 'polymarket_bet_size':
						avg_bet = result.iloc[0].get('avg_bet_size', 'N/A')
						print(f"   🎯 Taille moyenne des paris Polymarket: {avg_bet}", file=stream)

		# Actifs
		coin_mapping = {'bitcoin': 'BTC', 'ethereum': 'ETH', 'solana': 'SOL', 'chainlink': 'LINK'}
		rows = []
		for coin_id, info in data.get('coins', {}).items():
			symbol = coin_mapping.get(coin_id)
			if symbol:
				change_icon = "🟢" if info.get('usd_24h_change', 0) >= 0 else "🔴"
				v_mc_ratio = info.get('usd_24h_vol', 0) / info.get('usd_market_cap', 1) if info.get('usd_market_cap', 0) > 0 else 0
				row = [symbol, f"${info.get('usd', 0):,.2f}", change_icon, f"{info.get('usd_24h_change', 0):+.2f}%", f"V/MC: {v_mc_ratio:.4f}"]
				# On-chain
				if symbol in ['BTC', 'ETH']:
					onchain_data = additional_data.get('onchain', {}).get(symbol, {}) if additional_data else {}
					if onchain_data:
						row.append(f"TXs={onchain_data.get('transaction_count','N/A')}, HashRate={onchain_data.get('hash_rate','N/A')}")
					deriv_data = additional_data.get('derivatives', {}).get(symbol, {}) if additional_data else {}
					if deriv_data:
						row.append(f"FR={deriv_data.get('funding_rate','N/A')}, OI={deriv_data.get('open_interest','N/A')}")
				rows.append(row)

		headers = ["Symbol", "Price", "Change", "24h %", "V/MC", "On-Chain", "Derivatives"]
		if self.use_tabulate:  # pragma: no cover - aspect présentation
			print(tabulate(rows, headers=headers, tablefmt="psql"), file=stream)
		else:
			df = pd.DataFrame(rows, columns=headers)
			print(df.to_string(index=False), file=stream)

		# Signaux
		if signals:
			print("\n🚦 SIGNALS:", file=stream)
			print(f"   Accumulation: {self.get_signal_emoji(signals.get('accumulation_signal', 0))} {signals.get('accumulation_signal', 0)}", file=stream)
			print(f"   Levier: {self.get_signal_emoji(signals.get('leverage_signal', 0))} {signals.get('leverage_signal', 0)}", file=stream)
			print(f"   Liquidité: {self.get_signal_emoji(signals.get('liquidity_signal', 0))} {signals.get('liquidity_signal', 0)}", file=stream)

		# Sentiment
		if fgi_data:
			sentiment_icon = "😨" if int(fgi_data.get('value', 50)) < 25 else "😊" if int(fgi_data.get('value', 50)) > 75 else "😐"
			print(f"\n🎭 SENTIMENT: {fgi_data.get('value', 'N/A')} {sentiment_icon} ({fgi_data.get('value_classification', 'N/A')})", file=stream)

	def get_signal_emoji(self, signal_value):
		if signal_value > 0:  # pragma: no cover - logique triviale
			return "🟢"
		elif signal_value < 0:  # pragma: no cover
			return "🔴"
		else:  # pragma: no cover
			return "🟡"
