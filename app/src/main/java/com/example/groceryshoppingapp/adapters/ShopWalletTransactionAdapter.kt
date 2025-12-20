package com.example.groceryshoppingapp.adapters

import android.graphics.Color
import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.databinding.ItemWalletTransactionBinding
import com.example.groceryshoppingapp.models.WalletTransaction

class ShopWalletTransactionAdapter(
    private val transactions: List<WalletTransaction>
) : RecyclerView.Adapter<ShopWalletTransactionAdapter.ViewHolder>() {

    inner class ViewHolder(val binding: ItemWalletTransactionBinding) :
        RecyclerView.ViewHolder(binding.root) {

        fun bind(tx: WalletTransaction) {
            binding.tvTransactionType.text = tx.type
            binding.tvTransactionDate.text = tx.dateTime

            when (tx.type.lowercase()) {

                "order income" -> {
                    binding.imgType.setImageResource(R.drawable.credit_icon)
                    binding.tvTransactionAmount.setTextColor(Color.parseColor("#4CAF50"))
                    binding.tvTransactionAmount.text = "+₹${tx.amount}"
                }

                "refund" -> {
                    binding.imgType.setImageResource(R.drawable.refund_icon)
                    binding.tvTransactionAmount.setTextColor(Color.parseColor("#F44336"))
                    binding.tvTransactionAmount.text = "-₹${tx.amount}"
                }

                "partial refund" -> {
                    val orange = Color.parseColor("#FF9800")
                    binding.imgType.setImageResource(R.drawable.refund_icon)
                    binding.tvTransactionAmount.setTextColor(orange)
                    binding.tvTransactionType.setTextColor(orange)
                    binding.tvTransactionAmount.text = "-₹${tx.amount}"
                }
            }
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
