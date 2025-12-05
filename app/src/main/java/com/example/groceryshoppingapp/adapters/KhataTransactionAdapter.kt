package com.example.groceryshoppingapp.adapters

import android.graphics.Color
import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.databinding.ItemKhataTransactionBinding
import com.example.groceryshoppingapp.models.KhataTransaction
import java.text.SimpleDateFormat
import java.util.*

class KhataTransactionAdapter(
    private val transactions: List<KhataTransaction>
) : RecyclerView.Adapter<KhataTransactionAdapter.ViewHolder>() {

    inner class ViewHolder(val binding: ItemKhataTransactionBinding) :
        RecyclerView.ViewHolder(binding.root) {

        fun bind(tx: KhataTransaction) {

            val ctx = binding.root.context

            // Timestamp
            val epochMillis = tx.getCreatedTimestamp()
            val sdf = SimpleDateFormat("dd MMM yyyy, hh:mm a", Locale.getDefault())
            sdf.timeZone = TimeZone.getTimeZone("Asia/Kolkata")
            binding.tvDate.text = sdf.format(Date(epochMillis))

            // Amount
            val amount = tx.amount ?: 0.0
            binding.tvAmount.text = "₹${String.format("%.2f", amount)}"

            // Note
            binding.tvNote.text = tx.note ?: ""

            // Type
            val type = tx.type?.lowercase() ?: ""

            when (type) {

                "debit" -> {
                    binding.tvType.text = "DEBIT"
                    binding.tvAmount.setTextColor(Color.parseColor("#D32F2F"))
                    binding.tvType.setBackgroundResource(R.drawable.bg_badge_due)
                }

                "credit" -> {
                    binding.tvType.text = "CREDIT"
                    binding.tvAmount.setTextColor(Color.parseColor("#2E7D32"))
                    binding.tvType.setBackgroundResource(R.drawable.bg_badge_advance)
                }

                "reject" -> {
                    // ⭐ Rejected Cash Payment – no balance change
                    binding.tvType.text = "REJECTED"
                    binding.tvAmount.setTextColor(Color.parseColor("#FF9800")) // Orange
                    binding.tvType.setBackgroundResource(R.drawable.bg_badge_yellow)
                }

                else -> {
                    binding.tvType.text = type.uppercase()
                    binding.tvAmount.setTextColor(Color.BLACK)
                    binding.tvType.setBackgroundResource(R.drawable.bg_badge_advance)
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
