package com.example.groceryshoppingapp.adapters

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.databinding.ItemKhataAccountBinding
import com.example.groceryshoppingapp.models.KhataAccount
import com.example.groceryshoppingapp.utils.SessionManager
import kotlin.math.abs

class KhataAccountAdapter(
    private val accounts: List<KhataAccount>,
    private val clickListener: (KhataAccount) -> Unit
) : RecyclerView.Adapter<KhataAccountAdapter.ViewHolder>() {

    inner class ViewHolder(val binding: ItemKhataAccountBinding) :
        RecyclerView.ViewHolder(binding.root) {

        fun bind(acc: KhataAccount) {
            val context = binding.root.context
            val role = SessionManager.getRole(context)

            // ✔ Bold + italic name
            binding.tvName.text = if (role == "customer") {
                acc.shopName ?: "Unknown Shop"
            } else {
                acc.customerName ?: "Unknown Customer"
            }
            binding.tvName.textSize = 18f
            binding.tvName.setTypeface(binding.tvName.typeface, android.graphics.Typeface.BOLD_ITALIC)

            binding.tvPhone.text = acc.phone?.let { "Phone: $it" } ?: "Phone: N/A"

            val bal = acc.balance ?: 0.0
            val absBal = abs(bal)

            // Amount Text = BIGGER ✔
            binding.tvBalance.textSize = 20f
            binding.tvBalance.text = when (role) {
                "customer" ->
                    if (bal > 0) "₹-${String.format("%.2f", absBal)}"
                    else if (bal < 0) "₹+${String.format("%.2f", absBal)}"
                    else "₹0.00"

                "shopowner" ->
                    if (bal > 0) "₹+${String.format("%.2f", absBal)}"
                    else if (bal < 0) "₹-${String.format("%.2f", absBal)}"
                    else "₹0.00"

                else -> "₹${String.format("%.2f", absBal)}"
            }

            // ✔ COLOR LOGIC
            if (role == "customer") {
                if (bal > 0) { // customer owes
                    binding.tvBalance.setTextColor(ContextCompat.getColor(context, R.color.khata_due_red))
                } else if (bal < 0) {
                    binding.tvBalance.setTextColor(ContextCompat.getColor(context, R.color.khata_advance_green))
                }
            } else { // shopowner
                if (bal > 0) { // receivable
                    binding.tvBalance.setTextColor(ContextCompat.getColor(context, R.color.khata_advance_green))
                } else if (bal < 0) { // payable
                    binding.tvBalance.setTextColor(ContextCompat.getColor(context, R.color.khata_due_red))
                }
            }

            // Badge styling
            if (bal > 0) {
                binding.tvStatusBadge.text = if (role == "customer") "DUE" else "RECEIVABLE"
                binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_badge_due)
            } else if (bal < 0) {
                binding.tvStatusBadge.text = if (role == "customer") "ADVANCE" else "PAYABLE"
                binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_badge_advance)
            } else {
                binding.tvStatusBadge.text = "CLEAR"
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
