package com.example.groceryshoppingapp.adapters

import android.graphics.Color
import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.databinding.ItemKhataTransactionBinding
import com.example.groceryshoppingapp.models.KhataTransaction

class KhataTransactionAdapter(
    private val transactions: List<KhataTransaction>
) : RecyclerView.Adapter<KhataTransactionAdapter.ViewHolder>() {

    inner class ViewHolder(val binding: ItemKhataTransactionBinding) :
        RecyclerView.ViewHolder(binding.root) {

        fun bind(tx: KhataTransaction) {
            val amount = tx.amount ?: 0.0
            val type = tx.type ?: ""

            binding.tvAmount.text = "₹${String.format("%.2f", amount)}"
            binding.tvDate.text = tx.createdAt ?: ""
            binding.tvNote.text = tx.note ?: ""

            val typeLower = type.lowercase()
            binding.tvType.text = type.uppercase()

            when (typeLower) {
                "debit" -> {
                    binding.tvAmount.setTextColor(Color.parseColor("#F44336")) // red
                    binding.tvType.setBackgroundResource(R.drawable.bg_khata_badge_due)
                }
                "credit" -> {
                    binding.tvAmount.setTextColor(Color.parseColor("#4CAF50")) // green
                    binding.tvType.setBackgroundResource(R.drawable.bg_khata_badge_clear)
                }
                else -> {
                    binding.tvAmount.setTextColor(Color.parseColor("#000000"))
                    binding.tvType.setBackgroundResource(R.drawable.bg_khata_badge_clear)
                }
            }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val binding = ItemKhataTransactionBinding.inflate(
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
