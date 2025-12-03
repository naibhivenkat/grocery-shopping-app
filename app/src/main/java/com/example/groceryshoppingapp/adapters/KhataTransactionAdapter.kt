package com.example.groceryshoppingapp.adapters

import android.graphics.Color
import android.view.LayoutInflater
import android.view.ViewGroup
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
            // Amount
            val amount = tx.amount ?: 0.0
            binding.tvAmount.text = "₹${String.format("%.2f", amount)}"

            // Date: createdAt is epoch millis in String
            val epochMillis = try {
                tx.createdAt?.toLong() ?: System.currentTimeMillis()
            } catch (e: Exception) {
                System.currentTimeMillis()
            }

            val sdf = SimpleDateFormat("dd MMM yyyy, hh:mm a", Locale.getDefault())
            sdf.timeZone = TimeZone.getTimeZone("Asia/Kolkata")
            binding.tvDate.text = sdf.format(Date(epochMillis))

            // Note
            binding.tvNote.text = tx.note ?: ""

            // Type + colors
            val typeLower = tx.type?.lowercase() ?: ""
            binding.tvType.text = typeLower.uppercase()

            when (typeLower) {
                "debit" -> {
                    // debit = customer owes more
                    binding.tvAmount.setTextColor(Color.parseColor("#D32F2F"))
                    binding.tvType.setBackgroundResource(R.drawable.bg_badge_due)
                }
                "credit" -> {
                    // credit = payment made
                    binding.tvAmount.setTextColor(Color.parseColor("#2E7D32"))
                    binding.tvType.setBackgroundResource(R.drawable.bg_badge_advance)
                }
                else -> {
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
