package com.example.groceryshoppingapp.adapters

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.databinding.ItemShopCartBinding
import com.example.groceryshoppingapp.models.CartItem

class ShopCartListAdapter(
    private val shopCarts: List<Triple<String, String, List<CartItem>>>,
    private val onShopSelected: (String, List<CartItem>) -> Unit
) : RecyclerView.Adapter<ShopCartListAdapter.ViewHolder>() {

    inner class ViewHolder(val binding: ItemShopCartBinding) : RecyclerView.ViewHolder(binding.root) {
        fun bind(shopId: String, shopName: String, cartItems: List<CartItem>) {
            binding.tvShopName.text = shopName
            val totalItems = cartItems.sumOf { it.quantity }
            val totalAmount = cartItems.sumOf { it.item.price * it.quantity }
            binding.tvCartSummary.text = "Items: $totalItems | Total: ₹%.2f".format(totalAmount)

            binding.root.setOnClickListener {
                onShopSelected(shopId, cartItems)
            }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val binding = ItemShopCartBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return ViewHolder(binding)
    }

    override fun getItemCount() = shopCarts.size

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val (shopId, shopName, cartItems) = shopCarts[position]
        holder.bind(shopId, shopName, cartItems)
    }
}
