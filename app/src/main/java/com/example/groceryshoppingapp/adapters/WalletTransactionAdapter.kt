package com.example.groceryshoppingapp.adapters

import android.graphics.Color
import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.databinding.ItemWalletTransactionBinding
import com.example.groceryshoppingapp.models.WalletTransaction

class WalletTransactionAdapter(
    private val transactions: List<WalletTransaction>,
    private val clickListener: (WalletTransaction) -> Unit
) : RecyclerView.Adapter<WalletTransactionAdapter.ViewHolder>() {

    inner class ViewHolder(val binding: ItemWalletTransactionBinding) :
        RecyclerView.ViewHolder(binding.root) {

        fun bind(tx: WalletTransaction) {

            binding.tvTransactionType.text = tx.type
            binding.tvTransactionDate.text = tx.dateTime

            when (tx.type.lowercase()) {
                "deposit" -> {
                    binding.imgType.setImageResource(R.drawable.credit_icon)
                    binding.tvTransactionAmount.setTextColor(Color.parseColor("#4CAF50"))
                    binding.tvTransactionAmount.text = "+₹${tx.amount}"
                }

                "payment" -> {
                    binding.imgType.setImageResource(R.drawable.debit_icon)
                    binding.tvTransactionAmount.setTextColor(Color.parseColor("#F44336"))
                    binding.tvTransactionAmount.text = "-₹${tx.amount}"
                }

                "refund" -> {
                    binding.imgType.setImageResource(R.drawable.refund_icon)
                    binding.tvTransactionAmount.setTextColor(Color.parseColor("#7C4DFF"))
                    binding.tvTransactionAmount.text = "+₹${tx.amount}"
                }
            }

            binding.root.setOnClickListener { clickListener(tx) }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val binding = ItemWalletTransactionBinding.inflate(
            LayoutInflater.from(parent.context),
            parent,
            false
        )
        return ViewHolder(binding)
    }

    override fun getItemCount() = transactions.size

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        holder.bind(transactions[position])
    }
}
