package com.example.groceryshoppingapp.adapters

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.databinding.ItemKhataAccountBinding
import com.example.groceryshoppingapp.models.KhataAccount

class KhataAccountAdapter(
    private val accounts: List<KhataAccount>,
    private val clickListener: (KhataAccount) -> Unit
) : RecyclerView.Adapter<KhataAccountAdapter.ViewHolder>() {

    inner class ViewHolder(val binding: ItemKhataAccountBinding) :
        RecyclerView.ViewHolder(binding.root) {

        fun bind(acc: KhataAccount) {

            val balance = acc.balance ?: 0.0   // SAFELY unwrap balance

            binding.tvName.text = acc.customerName ?: "Unknown"
            binding.tvPhone.text = acc.phone?.let { "Phone: $it" } ?: "Phone: N/A"
            binding.tvBalance.text = "₹${String.format("%.2f", balance)}"

            // Balance Badge
            when {
                balance > 0 -> {
                    binding.tvStatusBadge.text = "DUE"
                    binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_khata_badge_due)
                }
                balance < 0 -> {
                    binding.tvStatusBadge.text = "ADVANCE"
                    binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_khata_badge_clear)
                }
                else -> {
                    binding.tvStatusBadge.text = "CLEAR"
                    binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_khata_badge_clear)
                }
            }

            binding.root.setOnClickListener { clickListener(acc) }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val binding = ItemKhataAccountBinding.inflate(
            LayoutInflater.from(parent.context),
            parent,
            false
        )
        return ViewHolder(binding)
    }

    override fun getItemCount() = accounts.size

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        holder.bind(accounts[position])
    }
}
